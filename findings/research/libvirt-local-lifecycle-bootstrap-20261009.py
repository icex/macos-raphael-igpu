import fcntl,os,struct,subprocess
fd=os.open('/dev/net/tun',os.O_RDWR)
fcntl.ioctl(fd,0x400454ca,struct.pack('16sH',b'rgpu_tap',0x1002))
subprocess.run(['ip','link','set','rgpu_tap','up'],check=True)
if fd!=3:os.dup2(fd,3);os.close(fd)
os.set_inheritable(3,True)
os.setgroups([]);os.setgid(1000);os.setuid(1000)
os.execv('/usr/bin/python3',['python3','-B','/candidate/findings/research/libvirt-local-lifecycle-smoke-20261009.py'])
