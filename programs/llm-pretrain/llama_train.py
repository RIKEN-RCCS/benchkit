"""LLM pretraining throughput: a Llama-architecture decoder (transformers, random init from a
config) trained with DeepSpeed ZeRO-3 on synthetic tokens. One script for GPUs (bf16, NCCL)
and Fugaku (fp32, torch_fugaku's "fjmpi" backend).

Rank and world come from the environment (torchrun, or mpiexec + pf-run). Prints the time
to each start-up phase, per-step loss and time, and the FOM: train tokens/s over the steps
after --warmup.

  python llama_train.py --model 1b --dtype bf16 --micro-batch 8 --backend nccl
"""
import argparse
import json
import os
import time

T_START = time.perf_counter()

import torch  # noqa: E402
import torch.distributed as dist  # noqa: E402

# Llama 3.2-1B / 3.2-3B / 3.1-8B shapes; "tiny" is for checking the script.
MODELS = {
    "tiny": dict(hidden_size=256, intermediate_size=1024, num_hidden_layers=2, num_attention_heads=8,
                 num_key_value_heads=4, vocab_size=8192, tie_word_embeddings=True),
    "1b": dict(hidden_size=2048, intermediate_size=8192, num_hidden_layers=16, num_attention_heads=32,
               num_key_value_heads=8, vocab_size=128256, tie_word_embeddings=True),
    "3b": dict(hidden_size=3072, intermediate_size=8192, num_hidden_layers=28, num_attention_heads=24,
               num_key_value_heads=8, vocab_size=128256, tie_word_embeddings=True),
    "8b": dict(hidden_size=4096, intermediate_size=14336, num_hidden_layers=32, num_attention_heads=32,
               num_key_value_heads=8, vocab_size=128256, tie_word_embeddings=False),
}


def memlog(phase, step=None):
    """With MEMLOG=1, each node's first rank prints its RSS and the node's MemAvailable (GiB)."""
    if os.environ.get("MEMLOG") != "1" or int(os.environ.get("LOCAL_RANK", "0")) != 0:
        return
    rss = avail = -1.0
    try:
        with open("/proc/self/status") as f:
            rss = next(int(l.split()[1]) for l in f if l.startswith("VmRSS")) / 2**20
        with open("/proc/meminfo") as f:
            avail = next(int(l.split()[1]) for l in f if l.startswith("MemAvailable")) / 2**20
    except (OSError, StopIteration):
        pass
    print(json.dumps({"event": "mem", "rank": int(os.environ.get("RANK", "0")), "phase": phase, "step": step,
                      "rss_gb": round(rss, 2), "node_avail_gb": round(avail, 2)}), flush=True)


def log(rank, **kw):
    if rank == 0:
        print(json.dumps(kw), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="1b", choices=sorted(MODELS))
    p.add_argument("--seq", type=int, default=2048)
    p.add_argument("--micro-batch", type=int, default=1, help="sequences per rank per step")
    p.add_argument("--steps", type=int, default=10)
    p.add_argument("--warmup", type=int, default=3, help="steps excluded from the FOM")
    p.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    p.add_argument("--zero", type=int, default=3)
    p.add_argument("--backend", default="gloo", help="nccl on GPUs, fjmpi on Fugaku")
    p.add_argument("--checkpointing", action="store_true", help="activation checkpointing")
    p.add_argument("--profile", type=int, default=0, help="profile the last N steps on rank 0 (+ comms logger)")
    p.add_argument("--low-mem", action="store_true",
                   help="ZeRO-3 buffers sized for 8 GB per rank (DeepSpeed's defaults keep 1e9 parameters live)")
    a = p.parse_args()

    if a.backend == "fjmpi":
        import torch_fugaku

        torch_fugaku.register_backend()
    import deepspeed
    from transformers import LlamaConfig, LlamaForCausalLM
    from transformers.integrations import HfDeepSpeedConfig

    t0 = time.perf_counter()
    t_import = t0 - T_START
    deepspeed.init_distributed(dist_backend=a.backend)
    rank, world = dist.get_rank(), dist.get_world_size()
    gpu = torch.cuda.is_available()
    if gpu:
        torch.cuda.set_device(int(os.environ.get("LOCAL_RANK", 0)))
    t_pg = time.perf_counter() - t0

    cfg = {
        "train_micro_batch_size_per_gpu": a.micro_batch,
        "gradient_accumulation_steps": 1,
        "train_batch_size": a.micro_batch * world,
        "zero_optimization": {"stage": a.zero, "overlap_comm": gpu, **({
            "stage3_max_live_parameters": int(1e8), "stage3_max_reuse_distance": int(1e8),
            "stage3_prefetch_bucket_size": int(2e7), "reduce_bucket_size": int(5e7),
            "sub_group_size": int(1e8)} if a.low_mem else {})},
        "gradient_clipping": 1.0,
        "bf16": {"enabled": a.dtype == "bf16"},
        "steps_per_print": 10**9,
        "zero_allow_untested_optimizer": True,
        "zero_force_ds_cpu_optimizer": False,
    }
    if a.profile:
        cfg["comms_logger"] = {"enabled": True, "verbose": False, "prof_all": True}
    t0 = time.perf_counter()
    torch.manual_seed(0)
    mcfg = LlamaConfig(max_position_embeddings=a.seq, attn_implementation="sdpa", **MODELS[a.model])
    # With ZeRO-3, transformers builds the model partitioned and gathers each parameter for its
    # own initialisation (std 0.02); the object must stay alive until the model exists.
    hf_ds = HfDeepSpeedConfig(cfg) if a.zero == 3 else None  # noqa: F841
    model = LlamaForCausalLM(mcfg)
    if a.checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    nparams = sum(getattr(x, "ds_numel", x.numel()) for x in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.1, betas=(0.9, 0.95), fused=True)
    memlog("model built")
    engine, _, _, _ = deepspeed.initialize(model=model, optimizer=opt, config=cfg)
    memlog("engine ready")
    t_model = time.perf_counter() - t0
    dev = engine.device
    log(rank, event="setup", model=a.model, params=nparams, world=world, dtype=a.dtype, zero=a.zero,
        micro_batch=a.micro_batch, seq=a.seq, backend=a.backend, low_mem=a.low_mem, threads=torch.get_num_threads(),
        t_import_s=round(t_import, 2), t_process_group_s=round(t_pg, 2), t_model_s=round(t_model, 2))

    gen = torch.Generator().manual_seed(1 + rank)
    times = []
    prof = None
    for step in range(a.steps):
        if rank == 0 and a.profile and step == a.steps - a.profile:
            from torch.profiler import ProfilerActivity, profile

            prof = profile(activities=[ProfilerActivity.CPU] + ([ProfilerActivity.CUDA] if gpu else []))
            prof.__enter__()
        ids = torch.randint(0, mcfg.vocab_size, (a.micro_batch, a.seq), generator=gen).to(dev)
        if gpu:
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        loss = engine(input_ids=ids, labels=ids).loss
        if step < 2:
            memlog("forward", step)
        engine.backward(loss)
        if step < 2:
            memlog("backward", step)
        engine.step()
        if step < 2:
            memlog("step", step)
        lt = loss.detach().float().clone()
        dist.all_reduce(lt)
        dt = time.perf_counter() - t0
        times.append(dt)
        log(rank, event="step", step=step, loss=round(lt.item() / world, 6), time_s=round(dt, 3))

    if prof is not None:
        prof.__exit__(None, None, None)
        key = "self_cuda_time_total" if gpu else "self_cpu_time_total"
        print(prof.key_averages().table(sort_by=key, row_limit=30), flush=True)
    if a.profile:
        deepspeed.comm.log_summary()
    import resource

    rss = torch.tensor([resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20], device=dev)  # GiB
    dist.all_reduce(rss, op=dist.ReduceOp.MAX)
    steady = times[a.warmup:]
    tokens = a.micro_batch * a.seq * world
    tps = tokens * len(steady) / sum(steady)
    flop_per_token = 6 * nparams + 12 * mcfg.num_hidden_layers * mcfg.hidden_size * a.seq  # 6N + attention
    nodes = int(os.environ.get("NNODES", os.environ.get("PJM_NODE", "1")))
    log(rank, event="fom", tokens_per_s=round(tps, 1), tokens_per_s_per_node=round(tps / nodes, 1),
        tflops_per_node=round(tps * flop_per_token / nodes / 1e12, 3), nodes=nodes,
        first_step_s=round(times[0], 2), steady_step_s=round(sum(steady) / len(steady), 3),
        peak_device_mem_gb=round((torch.cuda.max_memory_allocated() if gpu else 0) / 2**30, 2),
        peak_rss_gb_max_rank=round(rss.item(), 2))


if __name__ == "__main__":
    main()
