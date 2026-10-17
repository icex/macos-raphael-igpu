/* Observation only; native IOAccelerator functions, not the Lilu-routed AMD entry. */
#pragma D option quiet
#pragma D option aggsize=4m
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelVidMemory4wireEv:return
{
    @wire_result[arg1 & 0xff] = count();
}
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelVidMemory4wireEv:return
/(arg1 & 0xff) == 0/
{
    @failed_wire_stack[stack(12)] = count();
}
fbt:com.apple.iokit.IOAcceleratorFamily2:_ZN16IOAccelResource28fallbackEv:return
{
    @fallback_result[arg1 & 0xff] = count();
}
tick-1sec
/++seconds >= 35/
{
    exit(0);
}
END
{
    printa("WIRE_RESULT result=%d count=%@d\n", @wire_result);
    printa("FALLBACK_RESULT result=%d count=%@d\n", @fallback_result);
    printf("FAILED_WIRE_STACKS\n");
    printa(@failed_wire_stack);
}
