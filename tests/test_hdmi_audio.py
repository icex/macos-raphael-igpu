import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class HdmiAudioTests(unittest.TestCase):
    def test_audio_identity_dma_power_and_reset_fail_closed(self):
        tool = load('hdmi-audio')
        good = dict(bdf=tool.BDF, vendor='0x1002', device='0x1640', driver='vfio-pci',
                    group='32', members=[tool.BDF], power='on', runtime='active',
                    reset_methods=[], accessible=True, pci_command=3)
        self.assertEqual(tool.errors(good), [])
        for key in good:
            bad = dict(good); bad.pop(key)
            self.assertTrue(tool.errors(bad), key)
        for key, value in [('pci_command',7), ('pci_command',65535),
                           ('driver','snd_hda_intel'), ('reset_methods',['pm']),
                           ('members',[tool.BDF,'0000:7b:00.2']), ('runtime','suspended')]:
            self.assertTrue(tool.errors(dict(good, **{key:value})), key)

    def test_exact_two_function_topology_required_only_when_selected(self):
        tool = load('experiment')
        options = dict(BOOTDISK_MODE='custom', NVRAM='stock', GENERIC_GRAPHICS='off',
                       GDB='on', AUDIO='usb', HDMI_AUDIO='on')
        self.assertEqual(tool.launch_options({'launch_options':options}), options)
        manifest = dict(image_id='img', gpu=True, vfio_device='0000:7b:00.0', launch_options=options)
        good = dict(image_id='img', graphics_args=['-vga','none','-display','none'],
                    vfio_args=['vfio-pci,host=0000:7b:00.0,bus=pcie.0,addr=0x6,multifunction=on',
                               'vfio-pci,host=0000:7b:00.1,bus=pcie.0,addr=0x6.0x1,x-pci-vendor-id=0x1002,x-pci-device-id=0xab28,rombar=0'],
                    pci_topology=[dict(model='vfio-pci',bus='pcie.0',slot=6,function=0),
                                  dict(model='vfio-pci',bus='pcie.0',slot=6,function=1),
                                  dict(model='usb-audio',bus='xhci.0')])
        self.assertEqual(tool.validate_running(manifest, good), [])
        for index, before, after in [(0,',multifunction=on',''),(1,'0xab28','0x1640'),
                                     (1,'7b:00.1','7b:00.2'),(1,'0x6.0x1','0x7')]:
            bad=copy.deepcopy(good);bad['vfio_args'][index]=bad['vfio_args'][index].replace(before,after)
            self.assertTrue(tool.validate_running(manifest,bad))
        for mutate in ('extra','missing','collision'):
            bad=copy.deepcopy(good)
            if mutate=='extra': bad['vfio_args'].append('vfio-pci,host=0000:7b:00.2')
            if mutate=='missing': bad['vfio_args'].pop()
            if mutate=='collision': bad['pci_topology'].append(dict(model='other',bus='pcie.0',slot=6,function=1))
            self.assertTrue(tool.validate_running(manifest,bad),mutate)
        plain=copy.deepcopy(manifest);plain['launch_options'].pop('HDMI_AUDIO')
        self.assertIn('vfio_device',tool.validate_running(plain,good))
        self.assertIn('unexpected_vfio_device',tool.validate_running(dict(manifest,gpu=False),good))
