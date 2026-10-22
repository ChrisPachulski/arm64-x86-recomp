/* Apple-arm64 variadic calls on the x86-64 host, for gdyld (gbridge.hpp) and any other host bridge that includes it.
   Apple arm64 passes every variadic argument in its own 8-byte stack slot (long double is double), so
   argument N of a call is va[N-1] whatever its type: positional %N$ and '*' widths read that slot directly.
   The format is walked exactly once into a growing buffer, so %n and every argument read happen once, in order.
   The includer defines die(const char*, uint64_t) before including this header. */
#ifndef GVARARGS_H
#define GVARARGS_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <wchar.h>
#define GSCAN_MAX 32                                          /* pointer slots handed to the host scanf */

static uint64_t gva_take(const char**pf,const uint64_t*va,unsigned*next){   /* after '*': '*N$' or the next slot */
  const char*q=*pf; unsigned v=0;
  while(*q>='0'&&*q<='9') v=v*10+(unsigned)(*q++-'0');
  if(*q=='$'&&q>*pf&&v){ *pf=q+1; return va[v-1]; }
  return va[(*next)++];
}

static void gbuf_need(char**b,size_t*cap,size_t len,size_t more){   /* room for len+more chars and a NUL */
  size_t c=*cap?*cap:256;
  while(c<len+more+1) c*=2;
  if(c!=*cap){ char*nb=(char*)realloc(*b,c); if(!nb) die("printf: out of memory",(uint64_t)c); *b=nb; *cap=c; }
}

static char*gfmt_alloc(const char*f,const uint64_t*va,size_t*len){   /* malloc'd full output; *len = its length */
  char*b=NULL; size_t n=0,cap=0; unsigned next=0;
  gbuf_need(&b,&cap,0,0);
  while(*f){
    if(*f!='%'||f[1]=='%'){ char ch=*f; f+=(*f=='%')?2:1; gbuf_need(&b,&cap,n,1); b[n++]=ch; continue; }
    const char*s=f++; char spec[96]; size_t o=0; unsigned pos=0; int k=0; char lm[4]={0,0,0,0}; int nl=0;
    const char*q=f;
    while(*q>='0'&&*q<='9') pos=pos*10+(unsigned)(*q++-'0');
    if(*q=='$'&&q>f&&pos) f=q+1; else pos=0;
    spec[o++]='%';
    while(*f&&strchr("-+ #0'",*f)&&o<8) spec[o++]=*f++;
    if(*f=='*'){ f++; o+=(size_t)snprintf(spec+o,24,"%d",(int)gva_take(&f,va,&next)); }
    else while(*f>='0'&&*f<='9'&&o<32) spec[o++]=*f++;
    if(*f=='.'){
      f++;
      if(*f=='*'){ int p; f++; p=(int)gva_take(&f,va,&next); if(p>=0) o+=(size_t)snprintf(spec+o,24,".%d",p); }
      else { spec[o++]='.'; while(*f>='0'&&*f<='9'&&o<64) spec[o++]=*f++; }
    }
    while(*f&&strchr("hlLqjzt",*f)&&nl<3) lm[nl++]=*f++;
    char cv=*f;
    if(!cv) die("printf: truncated spec",(uint64_t)(uintptr_t)s);
    f++;
    if(o>80) die("printf: spec too long",(uint64_t)(uintptr_t)s);
    uint64_t a=pos?va[pos-1]:va[next++];
    if(cv=='n'){                                              /* store the count so far; no output */
      void*p=(void*)(uintptr_t)a;
      if(!strcmp(lm,"hh")) *(signed char*)p=(signed char)n; else if(!strcmp(lm,"h")) *(short*)p=(short)n;
      else if(nl) *(long long*)p=(long long)n; else *(int*)p=(int)n;
      continue;
    }
    int isfp=strchr("eEfFgGaA",cv)!=NULL;
    if(!isfp&&!strchr("diouxXcCsSpDOU",cv)) die("printf: unsupported conversion",(uint64_t)(uintptr_t)s);
    if(!isfp) for(int i=0;i<nl;i++) spec[o++]=lm[i];      /* 'L' dropped for floats: guest long double is a double */
    spec[o++]=cv; spec[o]=0;
    for(int pass=0;pass<2;pass++){                            /* a retry after growing re-reads only this argument */
      double d; memcpy(&d,&a,8);
      k=isfp?snprintf(b+n,cap-n,spec,d):snprintf(b+n,cap-n,spec,a);
      if(k<0) die("printf: encoding error",(uint64_t)(uintptr_t)s);
      if((size_t)k<cap-n) break;
      gbuf_need(&b,&cap,n,(size_t)k);
    }
    n+=(size_t)k;
  }
  b[n]=0; *len=n;
  return b;
}

static size_t gfmt(char*out,size_t cap,const char*f,const uint64_t*va){    /* snprintf semantics */
  size_t n; char*b=gfmt_alloc(f,va,&n);
  if(cap){ size_t m=n<cap?n:cap-1; memcpy(out,b,m); out[m]=0; }
  free(b);
  return n;
}

static int gvfprintf(FILE*fp,const char*f,const uint64_t*va){    /* no length cap: long output is never cut */
  size_t n; char*b=gfmt_alloc(f,va,&n);
  size_t w=fwrite(b,1,n,fp);
  free(b);
  return w==n?(int)n:-1;
}

static int gvasprintf(char**ret,const char*f,const uint64_t*va){
  size_t n; *ret=gfmt_alloc(f,va,&n);
  return (int)n;
}

/* swprintf family: the same walk over a wide format; each conversion is one host swprintf into the growing buffer */
static int gswfmt(wchar_t*out,size_t cap,const wchar_t*f,const uint64_t*va){
  size_t n=0,wcap=256; unsigned next=0; wchar_t*b=(wchar_t*)malloc(wcap*sizeof(wchar_t));
  if(!b) die("swprintf: out of memory",0);
  while(*f){
    if(n+2>wcap){ wcap*=2; b=(wchar_t*)realloc(b,wcap*sizeof(wchar_t)); if(!b) die("swprintf: out of memory",wcap); }
    if(*f!=L'%'||f[1]==L'%'){ wchar_t ch=*f; f+=(*f==L'%')?2:1; b[n++]=ch; continue; }
    const wchar_t*s=f++; wchar_t spec[96]; size_t o=0; unsigned pos=0; int nl=0, longs=0, shorts=0; const wchar_t*q=f;
    while(*q>=L'0'&&*q<=L'9') pos=pos*10+(unsigned)(*q++-L'0');
    if(*q==L'$'&&q>f&&pos) f=q+1; else pos=0;
    spec[o++]=L'%';
    while(*f&&wcschr(L"-+ #0'",*f)&&o<8) spec[o++]=*f++;
    if(*f==L'*'){ f++; o+=(size_t)swprintf(spec+o,24,L"%d",(int)va[next++]); }
    else while(*f>=L'0'&&*f<=L'9'&&o<32) spec[o++]=*f++;
    if(*f==L'.'){ spec[o++]=*f++; if(*f==L'*'){ f++; o+=(size_t)swprintf(spec+o,24,L"%d",(int)va[next++]); } else while(*f>=L'0'&&*f<=L'9'&&o<64) spec[o++]=*f++; }
    while(*f&&wcschr(L"hlLqjzt",*f)&&nl<3){ longs+=*f==L'l'; shorts+=*f==L'h'; if(*f!=L'L') spec[o++]=*f; f++; nl++; }   /* L: guest long double is a double */
    wchar_t cv=*f;
    if(!cv) die("swprintf: truncated spec",(uint64_t)(uintptr_t)s);
    f++;
    uint64_t a=pos?va[pos-1]:va[next++];
    if(cv==L'n'){                                             /* store the count so far at the modifier's width */
      void*p=(void*)(uintptr_t)a;
      if(shorts==2) *(signed char*)p=(signed char)n; else if(shorts==1) *(short*)p=(short)n;
      else if(nl) *(long long*)p=(long long)n; else *(int*)p=(int)n;
      continue;
    }
    int isfp=wcschr(L"eEfFgGaA",cv)!=NULL;
    if(!isfp&&!wcschr(L"diouxXcCsSp",cv)) die("swprintf: unsupported conversion",(uint64_t)(uintptr_t)s);
    spec[o++]=cv; spec[o]=0;
    for(;;){                                                  /* swprintf reports -1 when out of room: grow and retry */
      double d; memcpy(&d,&a,8);
      int k=isfp?swprintf(b+n,wcap-n,spec,d):(cv==L's'&&longs)?swprintf(b+n,wcap-n,spec,(const wchar_t*)(uintptr_t)a)
            :cv==L's'?swprintf(b+n,wcap-n,spec,(const char*)(uintptr_t)a):swprintf(b+n,wcap-n,spec,a);
      if(k>=0){ n+=(size_t)k; break; }
      if(wcap>((size_t)1<<26)) die("swprintf: conversion failed",(uint64_t)(uintptr_t)s);
      wcap*=2; b=(wchar_t*)realloc(b,wcap*sizeof(wchar_t)); if(!b) die("swprintf: out of memory",wcap);
    }
  }
  int r=n<cap?(int)n:-1;                                      /* the output and its NUL must fit */
  if(cap){ size_t m=n<cap?n:cap-1; memcpy(out,b,m*sizeof(wchar_t)); out[m]=0; }
  free(b);
  return r;
}

static int gscan(const char*s,FILE*fp,const char*f,const uint64_t*va){   /* scanf family: every argument is a pointer slot */
  size_t L=strlen(f), o=0; int na=0, r; char*fx=(char*)malloc(L+1);
  if(!fx) die("scanf: out of memory",(uint64_t)L);
  while(*f){
    int sup=0;
    if(*f!='%'){ fx[o++]=*f++; continue; }
    fx[o++]=*f++;
    if(*f=='%'){ fx[o++]=*f++; continue; }
    if(*f=='*'){ sup=1; fx[o++]=*f++; }
    while((*f>='0'&&*f<='9')||*f=='$') fx[o++]=*f++;
    while(*f&&strchr("hlLqjzt",*f)){ fx[o++]=(*f=='L')?'l':*f; f++; }   /* %Lf stores an 8-byte double on the guest */
    if(!*f) break;
    if(*f=='['){
      fx[o++]=*f++;
      if(*f=='^') fx[o++]=*f++;
      if(*f==']') fx[o++]=*f++;
      while(*f&&*f!=']') fx[o++]=*f++;
      if(*f) fx[o++]=*f++;
    } else fx[o++]=*f++;
    if(!sup) na++;
  }
  fx[o]=0;
  if(na>GSCAN_MAX) die("scanf: too many conversions",(uint64_t)na);
#define GS8(i) (void*)(uintptr_t)va[i],(void*)(uintptr_t)va[i+1],(void*)(uintptr_t)va[i+2],(void*)(uintptr_t)va[i+3],\
               (void*)(uintptr_t)va[i+4],(void*)(uintptr_t)va[i+5],(void*)(uintptr_t)va[i+6],(void*)(uintptr_t)va[i+7]
  r=fp?fscanf(fp,fx,GS8(0),GS8(8),GS8(16),GS8(24)):sscanf(s,fx,GS8(0),GS8(8),GS8(16),GS8(24));
#undef GS8
  free(fx);
  return r;
}
#endif
