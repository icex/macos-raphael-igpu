/* Correlate synchronous native reclaim calls and their nested wire failures. */
#pragma D option quiet
#pragma D option dynvarsize=4m
#pragma D option aggsize=4m
fbt:com.apple.iokit.IOAcceleratorFamily2:*freeWaitToPrepareVidMap*:entry
{
    self->depth++;
    maps[tid,self->depth]=arg1;
    failures[tid,self->depth]=0;
}
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelVidMemory4wireEv:return
/(arg1 & 0xff) == 0 && self->depth > 0/
{
    failures[tid,self->depth]++;
}
fbt:com.apple.iokit.IOAcceleratorFamily2:*freeWaitToPrepareVidMap*:return
/self->depth > 0/
{
    printf("RECLAIM_RETURN thread=%d depth=%d map=%p failed_wires=%d result=%d\n",tid,self->depth,maps[tid,self->depth],failures[tid,self->depth],arg1 & 0xff);
    @results[arg1 & 0xff,failures[tid,self->depth]]=count();
    maps[tid,self->depth]=0;
    failures[tid,self->depth]=0;
    self->depth--;
}
tick-1sec
/++seconds >= 35/
{
    exit(0);
}
END
{
    printa("RECLAIM_SUMMARY result=%d failed_wires=%d calls=%@d\n",@results);
}
