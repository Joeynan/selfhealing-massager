import sys,struct,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'WiFi摄像头版'))
import prepare_flash

def boot(sequence=1,app_address=0x200000):
    b=bytearray(b'\xff'*0x200000)
    b[0x8000:0x8020]=struct.pack('<HBBII16sI',0x50aa,0,16,app_address,0xc00000,b'ota_0',0)
    struct.pack_into('<I',b,0x10d000,sequence)
    return b

class FlashPreparationTests(unittest.TestCase):
    def setUp(self):
        # These are CLI/preflight tests for a historical uploader. Release
        # binaries are separate attachments and are not part of a fresh clone.
        verified=patch.object(prepare_flash,'verified_files',return_value=({},[]))
        verified.start();self.addCleanup(verified.stop)
    def test_default_command_uses_verified_preflight_without_opening_devices(self):
        with patch.object(prepare_flash.subprocess,'run') as run:
            prepare_flash.main([])
        run.assert_not_called()
    def test_partition_layout_is_checked_before_any_firmware_write(self):
        prepare_flash.verify_layout(boot())
        with self.assertRaises(ValueError):prepare_flash.verify_layout(boot(app_address=0x10000))
    def test_changed_active_ota_slot_is_not_overwritten(self):
        with self.assertRaises(ValueError):prepare_flash.verify_layout(boot(sequence=2))
    def test_duplicate_usb_port_is_rejected_before_device_access(self):
        with patch.object(prepare_flash.subprocess,'run') as run,self.assertRaises(SystemExit):
            prepare_flash.main(['--execute','--s3-port','/dev/cu.test','--vision-port','/dev/cu.test'])
        run.assert_not_called()
    def test_baud_must_be_one_of_the_supported_transport_rates(self):
        with patch.object(prepare_flash.subprocess,'run') as run,self.assertRaises(SystemExit):
            prepare_flash.main(['--baud','12345'])
        run.assert_not_called()
    def test_preflight_accepts_the_device_verified_medium_rate(self):
        with patch.object(prepare_flash.subprocess,'run') as run:
            prepare_flash.main(['--baud','230400'])
        run.assert_not_called()

if __name__=='__main__':unittest.main()
