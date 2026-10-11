import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "camera"))
from gesture_rules import Config,HandState


def f(ratios,angles=(170,170,170,170)):
    return {'pinch_ratio':ratios[0],'tip_thumb_ratios':list(ratios),'angles':list(angles),
            'folded':[a<145 for a in angles],'extended':[a>150 for a in angles],
            'normal_z':1,'thumb_open_ratio':.3,'thumb_length_ratio':1.2}


class KneadingUpdateTests(unittest.TestCase):
    def setUp(self):self.c=Config();self.s=HandState()

    def test_open_half_gather_sequence_is_first_kneading_cycle(self):
        self.s.classify(f([1.5,1.6,1.8,2]),'Left',100,self.c)
        self.s.classify(f([.72,.8,1,1.1],(166,165,168,162)),'Left',400,self.c)
        self.assertIn('kneading',self.s.classify(f([.15,.3,.4,.6],(138,130,130,139)),'Left',800,self.c))

    def test_open_preparation_does_not_use_up_movement_time(self):
        for t in (100,400,800,1200,1600,2000):
            self.s.classify(f([1.5,1.6,1.8,2]),'Left',t,self.c)
        self.s.classify(f([.72,.8,1,1.1],(166,165,168,162)),'Left',2300,self.c)
        self.assertIn('kneading',self.s.classify(f([.15,.3,.4,.6],(138,130,130,139)),'Left',2800,self.c))

    def test_one_bounded_pinky_outlier_does_not_block_gather(self):
        self.s.classify(f([1.5,1.6,1.8,2]),'Left',100,self.c)
        self.assertIn('kneading',self.s.classify(f([.2,.35,.5,.85],(140,135,135,150)),'Left',800,self.c))

    def test_two_open_fingers_do_not_count_as_all_finger_gather(self):
        self.s.classify(f([1.5,1.6,1.8,2]),'Left',100,self.c)
        self.assertNotIn('kneading',self.s.classify(f([.15,.3,1.4,1.6],(120,120,170,170)),'Left',800,self.c))

    def test_thumb_only_motion_does_not_count_as_kneading(self):
        self.s.classify(f([1.5,1.6,1.8,2]),'Left',100,self.c)
        self.assertNotIn('kneading',self.s.classify(f([.15,.3,.4,.5]),'Left',800,self.c))

    def test_held_gather_without_opening_never_triggers(self):
        for t in [100,400,800,1200,1600,2000]:
            self.assertNotIn('kneading',self.s.classify(f([.15,.3,.4,.6],(138,130,130,139)),'Left',t,self.c))

    def test_isolated_thumb_to_index_pinch_does_not_count_as_kneading(self):
        self.s.classify(f([1.5,1.6,1.8,2]),'Left',100,self.c)
        self.assertNotIn('kneading',self.s.classify(f([.1,1.4,1.5,1.6],(120,170,170,170)),'Left',800,self.c))

    def test_gather_with_noisy_extended_angles_is_not_light_pinch(self):
        result=self.s.classify(f([.17,.3,.4,.6],(151,142,151,160)),'Left',100,self.c)
        self.assertNotIn('pinch',result)
        self.assertNotIn('kneading',result)

    def test_large_outlier_is_not_a_valid_gather(self):
        self.s.classify(f([1.5,1.6,1.8,2]),'Left',100,self.c)
        self.assertNotIn('kneading',self.s.classify(f([.15,.3,.4,1.5],(138,130,130,139)),'Left',800,self.c))

    def test_closed_fist_thumb_adjustment_does_not_start_a_curl_cycle(self):
        opened=f([1.5,1.6,1.8,2],(140,140,140,140))
        opened.update(tip_mcp_ratios=[.6]*4,tip_cluster_ratio=1.1)
        self.s.classify(opened,'Left',100,self.c)
        closed=f([.6,.7,.8,.9],(125,125,125,125))
        closed.update(tip_mcp_ratios=[.6]*4,tip_cluster_ratio=.9)
        self.assertNotIn('kneading',self.s.classify(closed,'Left',800,self.c))

    def test_thumb_outside_curl_requires_finger_length_contraction(self):
        opened=f([1.5,1.6,1.8,2])
        opened.update(tip_mcp_ratios=[.7]*4,tip_cluster_ratio=1.1)
        self.s.classify(opened,'Left',100,self.c)
        closed=f([.6,.7,.8,.9],(125,125,125,125))
        closed.update(tip_mcp_ratios=[.6]*4,tip_cluster_ratio=.9)
        self.assertNotIn('kneading',self.s.classify(closed,'Left',800,self.c))


if __name__=='__main__':unittest.main()
