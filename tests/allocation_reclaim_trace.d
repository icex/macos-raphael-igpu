/* Correlate synchronous native reclaim calls and their nested wire failures. */
#pragma D option quiet
#pragma D option dynvarsize=4m
#pragma D option aggsize=4m
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelMemoryMap7prepareEv:entry
{
    self->mapdepth++;
    mapstack[tid,self->mapdepth]=arg0;
    wirefail[tid,self->mapdepth]=0;
}
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelVidMemory4wireEv:return
/(arg1 & 0xff) == 0 && self->mapdepth > 0/
{
    wirefail[tid,self->mapdepth]++;
}
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelMemoryMap7prepareEv:return
/self->mapdepth > 0/
{
    pending[tid,mapstack[tid,self->mapdepth]] = (arg1 & 0xff) ? 0 : wirefail[tid,self->mapdepth];
    mapstack[tid,self->mapdepth]=0;
    wirefail[tid,self->mapdepth]=0;
    self->mapdepth--;
}
fbt:com.apple.iokit.IOAcceleratorFamily2:*freeWaitToPrepareVidMap*:entry
{
    self->depth++;
    maps[tid,self->depth]=arg1;
    prior[tid,self->depth]=pending[tid,arg1];
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
    printf("RECLAIM_RETURN thread=%d depth=%d map=%p prior_failed_wires=%d failed_wires_inside=%d result=%d\n",tid,self->depth,maps[tid,self->depth],prior[tid,self->depth],failures[tid,self->depth],arg1 & 0xff);
    @results[arg1 & 0xff,prior[tid,self->depth],failures[tid,self->depth]]=count();
    maps[tid,self->depth]=0;
    prior[tid,self->depth]=0;
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
    printa("RECLAIM_SUMMARY result=%d prior_failed_wires=%d failed_wires_inside=%d calls=%@d\n",@results);
}
