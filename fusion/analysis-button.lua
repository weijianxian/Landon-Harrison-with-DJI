-- Runs in the native composition script context, on a separate script thread.
-- Video paths and options travel in JSON, never in a command string.
local M={}
function M.json(value)
    if type(value)=='string' then
        return '"'..value:gsub('[%z\1-\31\\"]',function(c)
            if c=='\\' then return '\\\\' elseif c=='"' then return '\\"' end
            return string.format('\\u%04x',c:byte())
        end)..'"'
    elseif type(value)=='number' or type(value)=='boolean' then return tostring(value)
    elseif type(value)=='table' then
        local out={}; for k,v in pairs(value) do out[#out+1]=M.json(k)..':'..M.json(v) end
        return '{'..table.concat(out,',')..'}'
    end
    error('Unsupported job data')
end
function M.utf16(text)
    local units={}; local i=1
    local function unit(n) units[#units+1]=n end
    while i<=#text do
        local a=text:byte(i); local n,len=a,1
        if a>=240 then n,len=a-240,4 elseif a>=224 then n,len=a-224,3 elseif a>=192 then n,len=a-192,2 end
        for j=1,len-1 do n=n*64+text:byte(i+j)-128 end
        if n>65535 then n=n-65536; unit(55296+math.floor(n/1024)); unit(56320+n%1024) else unit(n) end
        i=i+len
    end
    return units
end
function M.launch(python,script,jobPath,folder)
    local ffi=require('ffi')
    -- LuaJIT is provided by the host; ShellExecuteW starts pythonw directly.
    -- No terminal, shell command or Resolve Python configuration is involved.
    ffi.cdef[[intptr_t __stdcall ShellExecuteW(void*, const uint16_t*, const uint16_t*, const uint16_t*, const uint16_t*, int);]]
    local function wide(text)
        local units=M.utf16(text); local value=ffi.new('uint16_t[?]',#units+1)
        for i,n in ipairs(units) do value[i-1]=n end
        return value
    end
    assert(not script:find('["\r\n]') and not jobPath:find('["\r\n]'),'Invalid installed plugin path')
    local arguments='-I "'..script..'" --job "'..jobPath..'"'
    local result=ffi.load('shell32').ShellExecuteW(nil,nil,wide(python),wide(arguments),wide(folder),0)
    assert(tonumber(ffi.cast('intptr_t',result))>32,'Windows did not start the analysis process')
end
function M.node(c,token)
    local tool
    for _,candidate in pairs(c:GetToolList(false)) do
        if candidate:GetInput('AnalysisToken')==token then tool=candidate; break end
    end
    return assert(tool,'Analysis node is no longer available')
end
function M.disk(c,token)
    local tool=M.node(c,token)
    local directory=c:MapPath('DiskCaches:')
    assert(directory~='DiskCaches:','Fusion disk cache path is not configured')
    if not bmd.direxists(directory) then assert(bmd.createdir(directory),'Cannot create Fusion disk cache directory') end
    -- Let the host create and activate its own disk cache through its native UI.
    -- Do not call EnableDiskCache from the background analysis script thread.
    tool.Output:ShowDiskCacheDlg()
end
function M.run(c,token,job,folder)
    local tool=M.node(c,token)
    if tool:GetData('BirdDJI.AnalysisBusy') then print('Bird DJI: analysis already running'); return end
    tool:SetData('BirdDJI.AnalysisBusy',true)
    local function status(text) tool:SetInput('AnalysisStatus',text); print('Bird DJI: '..text) end
    status('正在分析，请等待…')
    local ok,err=pcall(function()
        local file=assert(io.open(folder..'/job-'..token..'.json','wb'))
        file:write(M.json(job)); file:close()
        local jobPath=folder..'/job-'..token..'.json'
        local python=folder..'/analyzer/.venv/Scripts/pythonw.exe'
        assert(io.open(python,'rb'),'插件分析环境未安装'):close()
        assert(bmd and bmd.wait,'Fusion background wait is unavailable')
        M.launch(python,folder..'/launch-analysis.py',jobPath,folder)
        local deadline=os.time()+86400
        while true do
            local done=io.open(jobPath..'.result','rb')
            if done then done:close(); break end
            assert(os.time()<deadline,'Analysis timed out; see task log')
            bmd.wait(.5)
        end
        local result=assert(io.open(jobPath..'.result','rb'),'分析程序未返回结果，请检查插件安装与任务日志')
        local code,path,message=result:read('*l'),result:read('*l'),result:read('*l'); result:close()
        assert(code=='OK',message or 'Analysis failed')
        assert(io.open(path,'rb'),'Analysis cache is missing'):close()
        tool:SetInput('CacheFile',path)
        tool:SetInput('CacheRevision',(tool:GetInput('CacheRevision') or 0)+1)
        status(message or '分析完成，已自动加载')
    end)
    if not ok then status('分析失败：'..tostring(err)) end
    tool:SetData('BirdDJI.AnalysisBusy',false)
end
return M
