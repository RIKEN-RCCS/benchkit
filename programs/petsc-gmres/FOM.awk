#!/usr/bin/awk -f
# Extract the per-routine detail behind the FOM from a PETSc -log_view file.
# Column positions are -log_view's fixed layout: $4 time(max), $6 flop(max),
# $21 total Mflop/s, $22 GPU Mflop/s. $4/$22 read "n/a" unless the run also
# passed -log_view_gpu_time, so run.sh passes it on every GPU system.
# Original by A. Suzuki, 25 Aug. 2026.
BEGIN{
   timeMatMult = 0.0; flopMatMult = 0.0; totalflopsMatMult = 0.0; gpuflopsMatMult = 0.0;
   timeKSPSolve = 0.0; flopKSPSolve = 0.0; totalflopsKSPSolve = 0.0; gpuflopsKSPSolve = 0.0;
   timeSFPack = 0.0;
   timeSFUnpack = 0.0;
}
# space is mandatory to exclude MatMult{Add,Transpose}
/^MatMult /{
   timeMatMult = $4; flopMatMult = $6; totalflopsMatMult = $21; gpuflopsMatMult = $22;
}
/^KSPSolve/{
   timeKSPSolve = $4; flopKSPSolve = $6; totalflopsKSPSolve = $21; gpuflopsKSPSolve = $22;
}
/^SFPack/{
   timeSFPack = $4;
}
/^SFUnpack/{
   timeSFUnpack = $4;
}
END{
   printf("#routine     \ttime(sec) \tflop      flop/s(total) flop/s(GPU)\n");
   printf("MatMult      \t%s \t%s \t%s \t%s\n", timeMatMult, flopMatMult, totalflopsMatMult, gpuflopsMatMult);
   printf("KSPSolve     \t%s \t%s \t%s \t%s\n", timeKSPSolve, flopKSPSolve, totalflopsKSPSolve, gpuflopsKSPSolve);
   printf("SFPack/Unpack\t%s\n", timeSFPack + timeSFUnpack);
}
