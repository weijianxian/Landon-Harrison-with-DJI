import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bird_dji.analysis import analyze
from bird_dji.motion import CameraMotion, Look
from bird_dji.pose import PersonBox, PoseTimeline, Scan
from tests.fusion.lua_runtime import Lua, load_fuse, MOCK_FUSION, ROOT


def sample_cache():
    frames = [dict(time=i/10,speed=2,altitude=3,heading=None,look=[.5,0],
                   visual_heading=30,pose_scan=1 if i==0 else 2 if i<4 else 0) for i in range(5)]
    boxes = [dict(track=7,x1=.4,y1=.4,x2=.6,y2=.6)]
    moved = [dict(track=7,x1=.6,y1=.4,x2=.8,y2=.6)]
    return dict(schema="bird-dji.fusion.v1",coordinates="normalized-top-left",width=1920,height=1080,
                fps="10/1",duration=.5,frame_count=5,max_speed=4,frames=frames,
                scans=[dict(time=0,points=[[.5,.5,.9]],boxes=boxes),
                       dict(time=.1,points=[[.7,.5,.9]],boxes=moved)])


class AnalysisTests(unittest.TestCase):
    def test_rounded_container_duration_does_not_add_a_phantom_frame(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            video,srt,output = root/'clip.mp4',root/'clip.srt',root/'cache.json'
            video.write_bytes(b'fixture')
            srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n[rel_alt: 2]\n',encoding='utf-8')
            with patch('bird_dji.analysis.probe',return_value=dict(width=1920,height=1080,
                       fps='10/1',duration=.500001,frames=5)), \
                 patch('bird_dji.analysis.CameraMotion.read',return_value=CameraMotion([Look(0)])):
                data = analyze(video,srt,output)
            self.assertEqual(data['frame_count'],5)
            self.assertEqual(data['frames'][-1]['time'],.4)

    def test_cache_timing_missing_values_and_scan_expiry(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            video,srt,output = root/"clip.mp4",root/"clip.srt",root/"analysis.json"
            video.write_bytes(b"fixture")
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n[rel_alt: 2]\n",encoding="utf-8")
            motion = CameraMotion([Look(0,0,0,0),Look(.5,1,0,30)])
            pose = PoseTimeline([Scan(0,[(.5,.5,.9)],1,[PersonBox(1,.4,.4,.6,.6)]),Scan(.2,[],0,[])],.2)
            with patch('bird_dji.analysis.probe',return_value=dict(width=1920,height=1080,fps="10/1",duration=.5)), \
                 patch('bird_dji.analysis.CameraMotion.read',return_value=motion), \
                 patch('bird_dji.analysis.PoseTimeline.read',return_value=pose):
                data = analyze(video,srt,output,pose_model=root/"model.pt",pose_interval=.2)
                self.assertEqual([f['pose_scan'] for f in data['frames']],[1,1,2,2,0])
                self.assertIsNone(data['frames'][0]['speed'])
                self.assertAlmostEqual(data['frames'][2]['look'][0],.4)
                self.assertEqual(json.loads(output.read_text()),data)
                self.assertEqual(data['source'],dict(video='clip.mp4',srt='clip.srt'))
                with self.assertRaisesRegex(ValueError,'已存在'):
                    analyze(video,srt,output)


class FuseTests(unittest.TestCase):
    def setUp(self):
        try:
            self.lua = Lua()
        except (OSError,RuntimeError) as error:
            self.skipTest(str(error))
        self.addCleanup(self.lua.close)
        load_fuse(self.lua)
        raw = json.dumps(sample_cache(),ensure_ascii=False)
        self.lua.run("c=BirdDJI.validate(BirdDJI.decode("+json.dumps(raw)+")); p=BirdDJI.defaults(); p.EnableAlarm=0; p.ResultInterval=0")

    def test_json_is_data_only_and_null_and_unicode_work(self):
        self.lua.run(r'''
            local B=BirdDJI
            assert(B.decode([["\ud83d\ude81"]])=='🚁')
            assert(#B.decode('[null,1]')==2)
            for _,bad in ipairs({'os.execute("bad")','[1,]','01','1.','+1','1e+','0x1','{} trailing'}) do
                assert(not pcall(B.decode,bad),'Accepted invalid JSON: '..bad)
            end
            local invalid=B.decode('[]')
            assert(not pcall(B.validate,invalid))
        ''')

    def test_follow_is_nearest_bounded_and_independent_of_seek_order(self):
        self.lua.run('''
            local B=BirdDJI; local follow=B.follow(c,p)
            assert(follow[1][3]==7 and follow[1][1]==.5)
            assert(follow[2][1]>.5 and (follow[2][1]-.5)*1920<=18.000001)
            assert(follow[5]==false)
            local function prompt(t)
                for _,s in ipairs(B.scene(c,t,p,1920,1080,follow)) do if s.tag=='prompt' then return s.points[1][1] end end
            end
            local first=prompt(.1); prompt(.3); prompt(0); assert(prompt(.1)==first)
            p.TargetMode=1; p.LookX=-1; p.AutoLook=0
            assert(B.follow(c,p)[1]==false)
        ''')

    def test_life_shrinks_symmetrically_and_alarm_can_be_disabled(self):
        self.lua.run('''
            local B=BirdDJI
            local function tagged(t,tag)
                for _,item in ipairs(B.scene(c,t,p,1920,1080)) do if item.tag==tag then return item end end
            end
            local full=tagged(0,'life-fill'); local half=tagged(.2,'life-fill')
            assert(math.abs((half.points[2][1]-half.points[1][1])*2-(full.points[2][1]-full.points[1][1]))<1e-8)
            assert((half.points[2][1]+half.points[1][1])/2==960)
            assert(not tagged(.4,'life-fill') and tagged(.4,'life-rail'))
            assert(not tagged(.3,'alarm-badge'))
            p.EnableAlarm=1; p.AlarmAt=.2
            assert(tagged(.4,'alarm-badge'))
            local red=tagged(.4,'reticle'); assert(red.color[1]>red.color[2] and red.width<4)
        ''')

    def test_layout_visibility_and_cache_end(self):
        self.lua.run('''
            local B=BirdDJI
            p.CenterX=.7; p.CenterY=.4; p.AutoLook=0; p.RingRadius=30
            for _,item in ipairs(B.scene(c,0,p,1920,1080)) do
                if item.tag=='reticle' then assert(math.abs(item.points[1][1]-(.7*1920+30))<1e-8) end
            end
            p.ShowReticle=0; p.ShowKeypoints=0; p.ShowPrompt=0
            for _,item in ipairs(B.scene(c,0,p,1920,1080)) do
                assert(item.tag~='reticle' and item.tag~='keypoint' and item.tag~='prompt')
            end
            assert(#B.scene(c,-.1,p,1920,1080)==0 and #B.scene(c,.5,p,1920,1080)==0)
        ''')

    def test_sampling_holds_people_without_freezing_motion_or_mutating_cache(self):
        self.lua.run('''
            local B=BirdDJI
            local function point(t)
                for _,s in ipairs(B.scene(c,t,p,1920,1080)) do
                    if s.tag=='keypoint' then return s.points[1][1] end
                end
            end
            local raw=point(.2); p.ResultInterval=.5
            local held=point(.2); assert(raw~=held and held==point(0))
            assert(point(.4)==held)
            assert(B.follow(c,p)[5]~=false)
            assert(c.frames[3].pose_scan==2 and c.frames[5].pose_scan==0)
            p.ResultInterval=0; assert(point(.2)==raw and not point(.4))
        ''')

    def test_one_second_interval_updates_at_boundaries_and_does_not_freeze_hud(self):
        cache = sample_cache()
        cache.update(duration=2.1, frame_count=21)
        cache['frames'] = [dict(cache['frames'][0],time=i/10,look=[i/20,0],
                                pose_scan=1 if i==0 else 2 if i<20 else 0) for i in range(21)]
        self.lua.run('c=BirdDJI.validate(BirdDJI.decode('+json.dumps(json.dumps(cache))+')); '+'''
            local B=BirdDJI; p=B.defaults(); p.EnableAlarm=0
            assert(p.ResultInterval==1)
            local function item(t,tag)
                for _,s in ipairs(B.scene(c,t,p,1920,1080)) do if s.tag==tag then return s end end
            end
            local start=item(0,'keypoint').points[1][1]
            assert(item(.9,'keypoint').points[1][1]==start)
            local next=item(1,'keypoint').points[1][1]
            assert(next~=start and item(1.9,'keypoint').points[1][1]==next)
            assert(not item(2,'keypoint'))
            assert(item(.9,'reticle').points[1][1]~=item(0,'reticle').points[1][1])
            local full=item(0,'life-fill'); local later=item(.9,'life-fill')
            assert(later.points[2][1]-later.points[1][1]<full.points[2][1]-full.points[1][1])
            assert(#c.scans==2 and c.frames[10].pose_scan==2)
        ''')

    def test_separate_layers_partition_all_geometry_including_alarm_and_prompt(self):
        self.lua.run('''
            local B=BirdDJI
            p.EnableAlarm=1; p.AlarmAt=0
            p.LayerMode=0; local all=B.scene(c,.2,p,1920,1080)
            p.LayerMode=1; local hud=B.scene(c,.2,p,1920,1080)
            p.LayerMode=2; local people=B.scene(c,.2,p,1920,1080)
            assert(#hud>0 and #people>0 and #hud+#people==#all)
            local function has(items,tag)
                for _,item in ipairs(items) do if item.tag==tag then return true end end
                return false
            end
            assert(has(hud,'reticle') and has(hud,'life-fill') and has(hud,'alarm-badge'))
            assert(not has(hud,'keypoint') and not has(hud,'prompt'))
            assert(has(people,'keypoint') and has(people,'prompt'))
            assert(not has(people,'reticle') and not has(people,'life-fill') and not has(people,'alarm-badge'))
            local function same(a,b)
                if type(a)~=type(b) then return false end
                if type(a)~='table' then return a==b end
                for k,v in pairs(a) do if not same(v,b[k]) then return false end end
                for k in pairs(b) do if a[k]==nil then return false end end
                return true
            end
            for _,items in ipairs({hud,people}) do
                for _,part in ipairs(items) do
                    local found=false
                    for _,item in ipairs(all) do if same(part,item) then found=true; break end end
                    assert(found,'Layer geometry or color differs from combined output')
                end
            end
            p.ShowKeypoints=0; p.ShowPrompt=0
            assert(#B.scene(c,.2,p,1920,1080)==0)
        ''')

    def test_analysis_command_encoding_and_callback_status(self):
        helper = (ROOT/'fusion/analysis-button.lua').as_posix()
        path = 'C:/中文目录/🚁/analysis.py'
        encoded = self.lua.run('m=assert(loadfile('+json.dumps(helper)+'))(); return table.concat(m.utf16('+json.dumps(path,ensure_ascii=False)+'),",")')
        raw = b''.join(int(n).to_bytes(2,'little') for n in encoded.split(','))
        self.assertEqual(raw.decode('utf-16-le'),path)
        self.lua.run(MOCK_FUSION+'''
            Create(); assert(not _inputs.RepositoryPath)
            self.Comp.Execute=function() error('Initial notification must not launch analysis') end
            assert(not _inputs.VideoFile and not _inputs.AnalysisDevice and not _inputs.CacheDirectory)
            assert(_inputs.DetectionRate.attrs.INP_Passive)
            NotifyChanged(InHUDDetectionRate,{Value='some text'},0)
            NotifyChanged(InHUDDetectionRate,{Value=.5},0)
            NotifyChanged(InGenerate,{Value=0},0)
            NotifyChanged(InGenerate,nil,0)
            _inputs.Background.value=Image{IMG_Width=1920,IMG_Height=1080}
            _inputs.Background.value.Metadata={Filename='test.mp4'}
            local code
            self.Comp.Execute=function(_,s) code=s end
            NotifyChanged(InGenerate,{Value=1},0)
            assert(code and code:find('bundle_dir=') and not code:find('repository='))
        ''')

    def test_native_control_and_process_adapter_without_resolve_api(self):
        self.lua.run(MOCK_FUSION+'''
            Create(); assert(#_pages==0 and #_nests==11)
            assert(_inputs.Transparent.nest=='LayoutGroup' and _inputs.LineWidth.nest=='LayoutGroup')
            assert(_inputs.ResultInterval.nest=='PeopleGroup' and _inputs.ResultInterval.value==1)
            assert(_inputs.Font.attrs.INPS_DefaultText=='Microsoft YaHei')
            Process(_req); assert(_lastImage.draws>50 and _lastImage.cleared)
            assert(_outputs.OutputHUD.cleared and _outputs.OutputPeople.cleared)
            assert(_outputs.OutputHUD.draws>50 and _outputs.OutputPeople.draws==0)
            _inputs.Background.value=Image{IMG_Width=1280,IMG_Height=720}
            Process(_req); assert(_lastImage.copied and not _lastImage.cleared)
            assert(_outputs.OutputHUD.Width==1280 and _outputs.OutputPeople.Height==720)
            _inputs.Transparent.value=1; Process(_req); assert(_lastImage.cleared)
            _req.IsPreCalc=function() return true end
            Process(_req); assert(_lastImage.draws==0 and _lastImage.noData and not _lastImage.copied)
            assert(_outputs.OutputHUD.noData and _outputs.OutputPeople.noData)
            _req.IsPreCalc=function() return false end
            _inputs.CacheFile.value='missing-cache.json'
            Process(_req); assert(_lastImage.draws==1)
        ''')

    def test_native_disk_cache_uses_host_dialog_instead_of_background_activation(self):
        helper = (ROOT/'fusion/analysis-button.lua').as_posix()
        self.lua.run('m=assert(loadfile('+json.dumps(helper)+'))(); '+'''
            local opened=false; local created
            bmd={direxists=function() return false end,createdir=function(path) created=path; return true end}
            local comp={MapPath=function(_,path) return path:gsub('DiskCaches:','/native/Fusion/') end}
            local tool={Output={}}
            function tool:GetInput(k) return k=='AnalysisToken' and 'test-node' or nil end
            function tool.Output:EnableDiskCache(enable,path,lock,branch,delete,prerender,network)
                error('Do not activate disk cache on the background analysis thread')
            end
            function tool.Output:ShowDiskCacheDlg() opened=true end
            comp.GetToolList=function() return {tool} end
            m.disk(comp,'test-node')
            assert(opened and created=='/native/Fusion/')
        ''')
