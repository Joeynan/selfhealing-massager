import builtins, hashlib, importlib.util, inspect, io, json, sys, tempfile, unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('flash_release', ROOT/'flash_release.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ReleaseTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  data=bytearray(96);data[0]=0xe9;data[12]=9
  (self.root/'app.bin').write_bytes(data)
  self.manifest={'build_verified':True,'app':'app.bin','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'address':'0x200000','chip':'esp32s3','device_mac':'10:b4:1d:e6:00:9c'}
 def tearDown(self):self.tmp.cleanup()
 def validate(self):
  (self.root/'release-manifest.json').write_text(json.dumps(self.manifest));return m.validate(self.root)
 def test_only_application_partition(self):
  self.assertEqual(self.validate()[1]['address'],'0x200000')
  self.manifest['address']='0x0'
  with self.assertRaises(ValueError):self.validate()
 def test_no_unbuilt_or_tampered_image(self):
  self.manifest['build_verified']=False
  with self.assertRaises(ValueError):self.validate()
  self.manifest['build_verified']=True;(self.root/'app.bin').write_bytes(b'x'*96)
  with self.assertRaises(ValueError):self.validate()
 def test_wrong_chip_and_path_escape(self):
  self.manifest['chip']='esp8266'
  with self.assertRaises(ValueError):self.validate()
  self.manifest['chip']='esp32s3';self.manifest['app']='../app.bin'
  with self.assertRaises(ValueError):self.validate()
 def test_identity_checked(self):
  self.assertTrue(m.identity_matches('Chip is ESP32-S3\nMAC: 10:b4:1d:e6:00:9c',self.manifest['device_mac']))
  self.assertFalse(m.identity_matches('Chip is ESP32-S3\nMAC: e8:db:84:ea:6a:d8',self.manifest['device_mac']))
  self.assertFalse(m.identity_matches('Chip is ESP8266\nMAC: 10:b4:1d:e6:00:9c',self.manifest['device_mac']))
 def test_same_authenticated_connection_writes_only_app_then_verifies(self):
  data=b'the exact bytes that were validated';tool=FakeEsptool()
  m.flash_checked(data,self.manifest,'test-port',tool)
  self.assertEqual([e[0] for e in tool.events],['detect','enter','mac','stub','write','verify','reset','exit'])
  self.assertEqual(tool.events[0][1],dict(port='test-port',baud=115200,connect_mode='default-reset',connect_attempts=3))
  write,verify=tool.events[4],tool.events[5]
  self.assertIs(write[1],tool.stub);self.assertIs(verify[1],tool.stub)
  self.assertIs(tool.stub.connection,tool.device.connection)
  self.assertEqual(write[2],[(0x200000,data)]);self.assertEqual(verify[2],[(0x200000,data)])
  self.assertIs(write[2][0][1],data);self.assertIs(verify[2][0][1],data)
  self.assertEqual(write[3],dict(compress=True,erase_all=False,force=False,flash_freq='keep',flash_mode='keep',flash_size='keep'))
  self.assertEqual(verify[3],dict(flash_freq='keep',flash_mode='keep',flash_size='keep'))
 def test_wrong_mac_or_chip_cannot_load_stub_or_write(self):
  for chip,mac,expected in [('ESP32-S3','00:11:22:33:44:55',['detect','enter','mac','exit']),('ESP8266',m.TARGET_MAC,['detect','enter','exit'])]:
   with self.subTest(chip=chip,mac=mac):
    tool=FakeEsptool(chip,mac)
    with self.assertRaises(ValueError):m.flash_checked(b'bytes',self.manifest,'test-port',tool)
    self.assertEqual([e[0] for e in tool.events],expected)
 def test_failed_write_or_verify_closes_connection_without_reset(self):
  for failure in ['write','verify']:
   with self.subTest(failure=failure):
    tool=FakeEsptool(failure=failure)
    with self.assertRaises(RuntimeError):m.flash_checked(b'bytes',self.manifest,'test-port',tool)
    names=[e[0] for e in tool.events]
    self.assertEqual(names[-1],'exit');self.assertNotIn('reset',names)
    if failure=='write':self.assertNotIn('verify',names)
 def test_dry_run_never_imports_hardware_libraries(self):
  self.validate();original_import=builtins.__import__
  def guarded_import(name,*args,**kwargs):
   if name.split('.')[0] in ('esptool','serial'):
    self.fail('dry-run attempted to import a hardware library: '+name)
   return original_import(name,*args,**kwargs)
  with patch.object(sys,'argv',['flash_release.py','--root',str(self.root),'--dry-run']),patch('builtins.__import__',side_effect=guarded_import),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
   self.assertEqual(m.main(),0)
 def test_esptool_540_accepts_actual_api_arguments_without_connecting(self):
  if importlib.util.find_spec('esptool') is None:self.skipTest('esptool is not installed')
  import esptool
  if esptool.__version__!='5.4.0':self.skipTest('test requires the pinned esptool 5.4.0')
  options=dict(flash_freq='keep',flash_mode='keep',flash_size='keep')
  inspect.signature(esptool.detect_chip).bind(port='test-port',baud=115200,connect_mode='default-reset',connect_attempts=3)
  inspect.signature(esptool.run_stub).bind(object())
  inspect.signature(esptool.write_flash).bind(object(),[(0x200000,b'bytes')],compress=True,erase_all=False,force=False,**options)
  inspect.signature(esptool.verify_flash).bind(object(),[(0x200000,b'bytes')],**options)

class FakeDevice:
 def __init__(self,tool,chip,mac,connection=None):
  self.tool=tool;self.CHIP_NAME=chip;self.mac=mac;self.connection=connection if connection is not None else object()
 def __enter__(self):self.tool.events.append(('enter',self));return self
 def __exit__(self,*args):self.tool.events.append(('exit',self))
 def read_mac(self):self.tool.events.append(('mac',self));return tuple(int(v,16) for v in self.mac.split(':'))
 def hard_reset(self):self.tool.events.append(('reset',self))

class FakeEsptool:
 def __init__(self,chip='ESP32-S3',mac=m.TARGET_MAC,failure=None):
  self.events=[];self.failure=failure;self.device=FakeDevice(self,chip,mac);self.stub=None
 def detect_chip(self,**kwargs):self.events.append(('detect',kwargs));return self.device
 def run_stub(self,device):
  self.events.append(('stub',device));assert device is self.device
  self.stub=FakeDevice(self,device.CHIP_NAME,device.mac,device.connection);return self.stub
 def write_flash(self,device,images,**kwargs):
  self.events.append(('write',device,images,kwargs))
  if self.failure=='write':raise RuntimeError('write failed')
 def verify_flash(self,device,images,**kwargs):
  self.events.append(('verify',device,images,kwargs))
  if self.failure=='verify':raise RuntimeError('verify failed')
if __name__=='__main__':unittest.main()
