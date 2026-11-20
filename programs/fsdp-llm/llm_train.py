"""LLM pretraining throughput with PyTorch FSDP2 (fully_shard), optionally with tensor parallel
(DTensor) inside each node (--tp > 1). A Llama-architecture decoder from transformers, built on
the meta device, materialized as shards with random init, trained on synthetic tokens. One
script for GPUs (bf16 compute, NCCL), Genoa (fp32, gloo) and Fugaku (fp32, torch_fugaku's
"fjmpi" backend).

- Each decoder layer: q/k/v, gate/up column-parallel; o, down row-parallel.
- Embedding, lm_head and the loss are vocab-parallel (loss_parallel), so no rank holds the
  whole [vocab, hidden] weight or the [tokens, vocab] logits.
- --sp: the residual stream, norms and checkpointed layer inputs are sharded along the
  sequence inside the tensor-parallel group.
- fully_shard over the data-parallel mesh dimension per decoder layer, for the embedding, for
  lm_head, then the root; activation checkpointing per layer.

Every rank of a tensor-parallel group trains on the same batch. Rank and world come from the
environment (torchrun, or mpiexec + pf-run). Prints JSON events: setup, per-step loss and time,
and the FOM, train tokens/s over the steps after --warmup.

  torchrun --nproc_per_node 4 llm_train.py --model tiny --tp 4 --backend nccl --dtype bf16
"""
import argparse
import json
import os
import resource
import time
import types

T_START = time.perf_counter()

import torch  # noqa: E402
import torch.distributed as dist  # noqa: E402
import torch.nn.functional as F  # noqa: E402

# "1b" is Llama 3.2-1B's shape, the size every system can train. "30b" is the GPT-30B
# configuration in Fugaku-LLM's DeepSpeedFugaku (48 layers, hidden 6912, 72 heads, GPT-2's
# vocabulary padded to 50304) as a Llama: full multi-head attention and a SwiGLU MLP of 2/3 x 4h,
# so each layer has GPT's 12 h^2 weights. Embeddings are untied, so tensor parallel shards them
# separately. "tiny" is for checking the script.
MODELS = {
    "tiny": dict(hidden_size=256, intermediate_size=704, num_hidden_layers=2, num_attention_heads=8,
                 num_key_value_heads=4, vocab_size=8192),
    "1b": dict(hidden_size=2048, intermediate_size=8192, num_hidden_layers=16, num_attention_heads=32,
               num_key_value_heads=8, vocab_size=128256),
    "30b": dict(hidden_size=6912, intermediate_size=18432, num_hidden_layers=48, num_attention_heads=72,
                num_key_value_heads=72, vocab_size=50304),
}


def log(rank, **kw):
    if rank == 0:
        print(json.dumps(kw), flush=True)


def lm_loss(model, ids):
    """Mean next-token cross-entropy over vocab-sharded logits; the parallel model's forward."""
    from torch.distributed.tensor.parallel import loss_parallel

    h = model.model(input_ids=ids).last_hidden_state
    logits = model.lm_head(h)  # with --tp > 1 a DTensor, Shard(-1): [b, s, vocab / tp] per rank
    labels = torch.cat([ids[:, 1:], ids.new_full((ids.shape[0], 1), -100)], 1)
    with loss_parallel():
        return F.cross_entropy(logits.flatten(0, 1).float(), labels.flatten(), ignore_index=-100)


def parallelize(model, mesh, sp, checkpointing, mp_policy):
    """Tensor parallel over mesh["tp"] (none with --tp 1), then FSDP2 over mesh["dp"], in place."""
    from torch.distributed.fsdp import fully_shard

    tp, dp = mesh["tp"], mesh["dp"]
    if tp.size() > 1:
        tensor_parallel(model, tp, sp)
    if checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    # Own FSDP units for the embedding and lm_head, so each is gathered only while it is used.
    for m in (*model.model.layers, model.model.embed_tokens, model.lm_head):
        fully_shard(m, mesh=dp, mp_policy=mp_policy)
    model.forward = types.MethodType(lm_loss, model)  # FSDP's root hooks run on model(...)
    fully_shard(model, mesh=dp, mp_policy=mp_policy)


def tensor_parallel(model, tp, sp):
    """The tensor-parallel plan over the "tp" mesh dimension, in place."""
    from torch.distributed.tensor import Replicate, Shard
    from torch.distributed.tensor.parallel import (ColwiseParallel, PrepareModuleInput, RowwiseParallel,
                                                   SequenceParallel, parallelize_module)

    # src_data_rank=None: each rank keeps its own chunk of the meta tensor rather than a scatter
    # from rank 0 (torch_fugaku's fjmpi backend has no scatter). With --sp the embedding output
    # stays whole, so transformers' mask and positions see the full sequence; layer 0 shards it.
    seq = Shard(1) if sp else Replicate()
    parallelize_module(model, tp, {
        "model.embed_tokens": RowwiseParallel(input_layouts=Replicate()),
        "lm_head": ColwiseParallel(input_layouts=seq, output_layouts=Shard(-1), use_local_output=False),
        **({"model.norm": SequenceParallel(use_local_output=True)} if sp else {}),
    }, src_data_rank=None)
    plan = {
        "self_attn.q_proj": ColwiseParallel(), "self_attn.k_proj": ColwiseParallel(),
        "self_attn.v_proj": ColwiseParallel(), "self_attn.o_proj": RowwiseParallel(output_layouts=seq),
        "mlp.gate_proj": ColwiseParallel(), "mlp.up_proj": ColwiseParallel(),
        "mlp.down_proj": RowwiseParallel(output_layouts=seq),
    }
    if sp:
        plan.update({
            "input_layernorm": SequenceParallel(use_local_output=True),
            "post_attention_layernorm": SequenceParallel(use_local_output=True),
            "self_attn": PrepareModuleInput(input_kwarg_layouts={"hidden_states": Shard(1)},
                                            desired_input_kwarg_layouts={"hidden_states": Replicate()},
                                            use_local_output=True),
            "mlp": PrepareModuleInput(input_layouts=(Shard(1),), desired_input_layouts=(Replicate(),),
                                      use_local_output=True),
        })
        parallelize_module(model.model.layers[0], tp, PrepareModuleInput(
            input_layouts=(Replicate(),), desired_input_layouts=(Shard(1),), use_local_output=True))
    for layer in model.model.layers:
        parallelize_module(layer, tp, plan, src_data_rank=None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="30b", choices=sorted(MODELS))
    p.add_argument("--seq", type=int, default=2048)
    p.add_argument("--micro-batch", type=int, default=1, help="sequences per tensor-parallel group per step")
    p.add_argument("--steps", type=int, default=5)
    p.add_argument("--warmup", type=int, default=2, help="steps excluded from the FOM")
    p.add_argument("--tp", type=int, default=4, help="tensor-parallel size: the ranks of one node")
    p.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"],
                   help="compute precision; parameters, gradient reduction and AdamW stay fp32")
    p.add_argument("--backend", default="nccl", help="nccl on GPUs, fjmpi on Fugaku")
    p.add_argument("--sp", action="store_true", help="sequence parallel within the tensor-parallel group")
    p.add_argument("--checkpointing", action="store_true", help="activation checkpointing per layer")
    a = p.parse_args()

    if a.backend == "fjmpi":
        import torch_fugaku

        torch_fugaku.register_backend()
    from torch.distributed.device_mesh import init_device_mesh
    from torch.distributed.fsdp import MixedPrecisionPolicy
    from torch.distributed.tensor.parallel import loss_parallel
    from transformers import LlamaConfig, LlamaForCausalLM
    from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding

    t0 = time.perf_counter()
    t_import = t0 - T_START
    gpu = torch.cuda.is_available()
    if gpu:
        torch.cuda.set_device(int(os.environ.get("LOCAL_RANK", 0)))
    # fjmpi: rank and size come from the MPI launcher (pf-run sets RANK/WORLD_SIZE) and the
    # rendezvous is over MPI ("fjmpi://"), with no TCP store, which failed from ~1000 ranks.
    dist.init_process_group(a.backend, init_method="fjmpi://" if a.backend == "fjmpi" else None)
    rank, world = dist.get_rank(), dist.get_world_size()
    assert world % a.tp == 0, (world, a.tp)
    dp_size = world // a.tp
    dev = "cuda" if gpu else "cpu"
    mesh = init_device_mesh(dev, (dp_size, a.tp), mesh_dim_names=("dp", "tp"))
    dp_rank = mesh["dp"].get_local_rank()
    t_pg = time.perf_counter() - t0

    t0 = time.perf_counter()
    cfg = LlamaConfig(max_position_embeddings=a.seq, attn_implementation="sdpa", tie_word_embeddings=False,
                      **MODELS[a.model])
    with torch.device("meta"):
        model = LlamaForCausalLM(cfg)
    mp = MixedPrecisionPolicy(param_dtype=torch.bfloat16 if a.dtype == "bf16" else torch.float32,
                              reduce_dtype=torch.float32)
    parallelize(model, mesh, a.sp, a.checkpointing, mp)
    # Allocate the shards and initialize as transformers' Llama does: N(0, 0.02), norms 1.
    torch.manual_seed(rank)
    model.to_empty(device=dev)
    with torch.no_grad():
        for name, prm in model.named_parameters():
            (prm.fill_(1.0) if "norm" in name else prm.normal_(0.0, cfg.initializer_range))
    model.model.rotary_emb = LlamaRotaryEmbedding(config=cfg, device=dev)
    model.train()
    nparams = sum(prm.numel() for prm in model.parameters())  # DTensor numel is the global size
    # foreach=False: the parameters live on two meshes (tp-only and dp x tp).
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.1, betas=(0.9, 0.95), foreach=False)
    t_model = time.perf_counter() - t0
    log(rank, event="setup", model=a.model, params=nparams, world=world, tp=a.tp, dp=dp_size, sp=a.sp,
        checkpointing=a.checkpointing, dtype=a.dtype, seq=a.seq, micro_batch=a.micro_batch, backend=a.backend,
        threads=torch.get_num_threads(), cpus=len(os.sched_getaffinity(0)),
        gpus=torch.cuda.device_count() if gpu else 0, t_import_s=round(t_import, 2), t_process_group_s=round(t_pg, 2),
        t_model_s=round(t_model, 2))

    gen = torch.Generator().manual_seed(1 + dp_rank)  # one batch per data-parallel rank
    times = []
    for step in range(a.steps):
        ids = torch.randint(0, cfg.vocab_size, (a.micro_batch, a.seq), generator=gen).to(dev)
        if gpu:
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        loss = model(ids)
        with loss_parallel():
            loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        lt = (loss.detach().full_tensor() if hasattr(loss, "full_tensor") else loss.detach()).float().clone()
        dist.all_reduce(lt)
        # .item() waits for the device, so reading it before the timer stops keeps that wait
        # inside the measured step.
        loss_val = lt.item() / world  # every tensor-parallel rank holds its group's loss
        dt = time.perf_counter() - t0
        times.append(dt)
        log(rank, event="step", step=step, loss=round(loss_val, 6), time_s=round(dt, 3))

    rss = torch.tensor([resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20], device=dev)  # GiB
    dist.all_reduce(rss, op=dist.ReduceOp.MAX)
    steady = times[a.warmup:]
    tps = a.micro_batch * a.seq * dp_size * len(steady) / sum(steady)
    flop_per_token = 6 * nparams + 12 * cfg.num_hidden_layers * cfg.hidden_size * a.seq  # 6N + attention
    nodes = int(os.environ.get("NNODES", "1"))
    log(rank, event="fom", tokens_per_s=round(tps, 2), tokens_per_s_per_node=round(tps / nodes, 2),
        tflops_per_node=round(tps * flop_per_token / nodes / 1e12, 3), nodes=nodes,
        first_step_s=round(times[0], 2), steady_step_s=round(sum(steady) / len(steady), 3),
        peak_device_mem_gb=round((torch.cuda.max_memory_allocated() if gpu else 0) / 2**30, 2),
        peak_rss_gb_max_rank=round(rss.item(), 2))
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
