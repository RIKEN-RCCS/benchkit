#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <mpi.h>
#include <omp.h>
#include <link.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
extern "C" {
void dgemm_(const char*,const char*,const int*,const int*,const int*,
            const double*,const double*,const int*,const double*,const int*,
            const double*,double*,const int*);
void dsyev_(const char*,const char*,const int*,double*,const int*,double*,double*,const int*,int*);
}
static int library(struct dl_phdr_info *info, size_t, void *context) {
    const char *p=info->dlpi_name;
    if (std::strstr(p,"libmpi") || std::strstr(p,"libpmix") ||
        std::strstr(p,"libnvpl") || std::strstr(p,"libgomp") || std::strstr(p,"libnvomp"))
        std::fprintf(static_cast<FILE*>(context),"%s\n",p);
    return 0;
}
int main(int argc,char **argv) {
    MPI_Init(&argc,&argv);
    int rank=0,size=0,sum=0,threads=0;
    MPI_Comm_rank(MPI_COMM_WORLD,&rank); MPI_Comm_size(MPI_COMM_WORLD,&size);
    if(argc!=2) MPI_Abort(MPI_COMM_WORLD,1);
    #pragma omp parallel reduction(+:threads)
    { threads += 1; }
    const int n=2; const double one=1,zero=0;
    const double a[]={1,2,3,4},b[]={1,0,0,1}; double c[4]={};
    const char normal='N',vectors='V',upper='U';
    dgemm_(&normal,&normal,&n,&n,&n,&one,a,&n,b,&n,&zero,c,&n);
    double matrix[]={2,1,1,2},eigen[2]={},work[32]={}; const int lwork=32; int info=-1;
    dsyev_(&vectors,&upper,&n,matrix,&n,eigen,work,&lwork,&info);
    bool good=size==4 && threads==18 && info==0;
    for(int i=0;i<4;i++) good=good && std::isfinite(c[i]) && std::abs(c[i]-a[i])<1e-12;
    good=good && std::abs(eigen[0]-1)<1e-12 && std::abs(eigen[1]-3)<1e-12;
    MPI_Allreduce(&rank,&sum,1,MPI_INT,MPI_SUM,MPI_COMM_WORLD);
    if(!good || sum!=6) MPI_Abort(MPI_COMM_WORLD,2);
    std::string path=std::string(argv[1])+"/rank."+std::to_string(rank)+".libraries.txt";
    FILE *out=std::fopen(path.c_str(),"w"); if(!out) MPI_Abort(MPI_COMM_WORLD,3);
    dl_iterate_phdr(library,out); std::fclose(out);
    std::printf("SBD_PREFLIGHT rank=%d ranks=%d threads=%d sum=%d blas=passed lapack=passed\n",rank,size,threads,sum);
    return MPI_Finalize()==MPI_SUCCESS ? 0 : 4;
}
