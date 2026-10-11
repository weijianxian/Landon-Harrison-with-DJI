"""Run pure Fuse logic in Lua 5.1 without automating Resolve or its Studio API."""
import ctypes
import ctypes.util
import os
from pathlib import Path


class Lua:
    def __init__(self):
        path = os.environ.get("BIRD_DJI_LUA_LIBRARY")
        if not path:
            candidate = Path("C:/Program Files/Blackmagic Design/DaVinci Resolve/lua5.1.dll")
            path = str(candidate) if candidate.exists() else ctypes.util.find_library("lua5.1")
        if not path:
            raise RuntimeError("Lua 5.1 runtime not found; set BIRD_DJI_LUA_LIBRARY")
        self.lib = ctypes.CDLL(path)
        self.lib.luaL_newstate.restype = ctypes.c_void_p
        self.lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        self.lib.luaL_loadstring.argtypes = [ctypes.c_void_p,ctypes.c_char_p]
        self.lib.lua_pcall.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int]
        self.lib.lua_tolstring.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_size_t)]
        self.lib.lua_tolstring.restype = ctypes.c_void_p
        self.lib.lua_settop.argtypes = [ctypes.c_void_p,ctypes.c_int]
        self.lib.lua_close.argtypes = [ctypes.c_void_p]
        self.state = self.lib.luaL_newstate()
        if not self.state:
            raise RuntimeError("Cannot allocate Lua state")
        self.lib.luaL_openlibs(self.state)

    def run(self,code):
        self.lib.lua_settop(self.state,0)
        status = self.lib.luaL_loadstring(self.state,code.encode("utf-8"))
        if not status:
            status = self.lib.lua_pcall(self.state,0,1,0)
        size = ctypes.c_size_t()
        pointer = self.lib.lua_tolstring(self.state,-1,ctypes.byref(size))
        result = ctypes.string_at(pointer,size.value).decode("utf-8") if pointer else None
        if status:
            raise RuntimeError(result or f"Lua error {status}")
        return result

    def close(self):
        if self.state:
            self.lib.lua_close(self.state)
            self.state = None


ROOT = Path(__file__).resolve().parents[2]
FUSE = ROOT/"fusion/BirdDJI.fuse"


def load_fuse(lua):
    lua.run("function FuRegisterClass(...) end\nCT_Tool=1\n"+FUSE.read_text(encoding="utf-8"))


MOCK_FUSION = r'''
local values={}
local pages={}
local nests={}
local nest
self={Comp={GlobalStart=1001,RenderStart=1050}}
function self.Comp:MapPath(path) return path end
function self.Comp:GetPrefs(key) assert(key=='Comp.FrameFormat.Rate'); return 30 end
function self:AddControlPage(name) pages[#pages+1]=name end
function self:BeginControlNest(label,id,expanded)
    assert(not nest,'Unclosed control group')
    nest=id; nests[#nests+1]={id=id,label=label,expanded=expanded}
end
function self:EndControlNest() assert(nest,'Missing control group'); nest=nil end
function self:AddInput(label,id,a)
    assert(not values[id],'Duplicate input: '..id)
    local value=a.LINKID_DataType=='Text' and a.INPS_DefaultText or a.INP_Default
    local input={attrs=a,value=value,nest=nest}
    function input:GetValue(req)
        if id=='Background' then return self.value end
        return {Value=self.value}
    end
    function input:GetSource(time) return self:GetValue({Time=time}) end
    function input:SetSource(value,time) self.value=value.Value end
    values[id]=input; return input
end
function self:AddOutput(label,id,a)
    return {Set=function(_,req,out) _outputs[id]=out; if id=='Output' then _lastImage=out end end}
end
_inputs=values; _pages=pages; _nests=nests; _outputs={}
local function shape()
    local s={}
    function s:MoveTo(x,y) assert(x==x and y==y) end
    function s:LineTo(x,y) assert(x==x and y==y) end
    function s:Close() end
    function s:OutlineOfShape(w,lt,jt,p,wm,f) assert(w>0); return self end
    function s:TransformOfShape(mat) return self end
    function s:AddShape(other) assert(other) end
    return s
end
Shape=shape
function Matrix4()
    return {Scale=function() end,Move=function() end}
end
function Pixel(p) return p end
function Text(value) return {Value=value} end
function FillStyle() return {} end
function ChannelStyle() return {} end
function ImageChannel(out,sampling)
    return {SetStyleFill=function() end,ShapeFill=function() end,
            PutToImage=function(_,mode,style)
                assert(mode=='CM_Merge' and style.Color.A>=0 and style.Color.A<=1)
                assert(style.Color.R<=style.Color.A and style.Color.G<=style.Color.A and style.Color.B<=style.Color.A,'Color must be premultiplied')
                out.draws=out.draws+1
            end}
end
FontManager={GetFontList=function() return {mock=true} end,ScanDir=function() end}
function TextStyleFont(font,style) assert(font~=''); return {} end
function TextStyleFontMetrics(font)
    return {Scale=1000,TextAscent=.064,CharacterWidth=function() return .06 end,
            GetCharacterShape=function(_,ch) assert(ch>=0); return shape() end}
end
function Image(a)
    local im={Width=a.IMG_Width or (a.IMG_Like and a.IMG_Like.Width) or 1920,
              Height=a.IMG_Height or (a.IMG_Like and a.IMG_Like.Height) or 1080,
              XScale=1,YScale=1,draws=0,noData=a.IMG_NoData}
    function im:Clear() self.cleared=true end
    function im:CopyOf() local copy=Image{IMG_Width=self.Width,IMG_Height=self.Height}; copy.copied=true; return copy end
    function im:Merge(fg,attrs)
        assert(next(attrs)==nil,'Use native premultiplied alpha-over defaults')
        assert(fg.cleared,'Layer must have a transparent background')
        self.draws=self.draws+fg.draws
    end
    return im
end
_req={Time=1001,IsQuick=function() return false end,IsPreCalc=function() return false end}
'''
