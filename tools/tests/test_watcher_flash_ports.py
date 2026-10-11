"""Flash entry port selection is offline; actual chip/MAC checks remain mandatory."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util,unittest
ROOT=Path(__file__).resolve().parents[2]
s=importlib.util.spec_from_file_location('watcher_flash',ROOT/'tools/flash_watcher.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def port(device,vid,pid,serial):return SimpleNamespace(device=device,vid=vid,pid=pid,serial_number=serial)
class PortTests(unittest.TestCase):
 def candidates(self,rows):
  self.assertTrue(callable(getattr(m,'candidate_ports',None)), 'Flash entry must recognize the Watcher USB bridge without bypassing identity checks')
  return m.candidate_ports(rows)
 def test_watcher_bridge_selects_controller_interface_only(self):
  rows=[port('/dev/cu.usbmodem5AF91645701',0x1a86,0x55d2,'5AF9164570'),port('/dev/cu.usbmodem5AF91645703',0x1a86,0x55d2,'5AF9164570')]
  self.assertEqual(self.candidates(rows),['/dev/cu.usbmodem5AF91645703'])
 def test_native_esp_usb_still_supported(self):
  self.assertEqual(self.candidates([port('/dev/cu.usbmodemTEST',0x303a,0x1001,'any')]),['/dev/cu.usbmodemTEST'])
 def test_unrelated_bridge_or_vision_port_rejected(self):
  rows=[port('/dev/cu.usbmodemUNKNOWN01',0x1a86,0x55d2,'UNKNOWN'),port('/dev/cu.usbmodem5AF91645701',0x1a86,0x55d2,'5AF9164570'),port('/dev/cu.usbserial1110',0x1a86,0x7523,'any')]
  self.assertEqual(self.candidates(rows),[])
 def test_ambiguous_candidates_are_not_collapsed(self):
  rows=[port('/dev/cu.usbmodemA',0x303a,0x1001,'A'),port('/dev/cu.usbmodemB',0x303a,0x1001,'B')]
  self.assertEqual(self.candidates(rows),['/dev/cu.usbmodemA','/dev/cu.usbmodemB'])

class SpiTests(unittest.TestCase):
 def test_authenticated_write_initializes_spi_before_write(self):
  self.assertTrue(callable(getattr(m,'SpiInitializedTool',None)), 'Public API requires SPI attachment after run_stub')
  spec=importlib.util.spec_from_file_location('release_tests',ROOT/'outputs/Watcher控制台/滚轮表情版/tests/test_flash_release.py')
  tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(tests)
  class Tool(tests.FakeEsptool):
   def attach_flash(self,device):self.events.append(('attach',device))
  tool=Tool();manifest={'device_mac':tests.m.TARGET_MAC}
  tests.m.flash_checked(b'validated bytes',manifest,'test-port',m.SpiInitializedTool(tool))
  self.assertEqual([row[0] for row in tool.events],['detect','enter','mac','stub','attach','write','verify','reset','exit'])
 def test_failed_spi_attachment_cannot_write(self):
  self.assertTrue(callable(getattr(m,'SpiInitializedTool',None)), 'Public API requires SPI attachment after run_stub')
  spec=importlib.util.spec_from_file_location('release_tests',ROOT/'outputs/Watcher控制台/滚轮表情版/tests/test_flash_release.py')
  tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(tests)
  class Tool(tests.FakeEsptool):
   def attach_flash(self,device):self.events.append(('attach',device));raise RuntimeError('SPI attachment failed')
  tool=Tool()
  with self.assertRaises(RuntimeError):tests.m.flash_checked(b'bytes',{'device_mac':tests.m.TARGET_MAC},'test-port',m.SpiInitializedTool(tool))
  self.assertEqual([row[0] for row in tool.events],['detect','enter','mac','stub','attach','exit'])

if __name__=='__main__':unittest.main()
