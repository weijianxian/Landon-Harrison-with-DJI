# DJI 游戏无人机 HUD

从 DJI 的 SRT 遥测自动绘制半透明白色 HUD：中心圆圈、顶部滑动方向刻度、SPD 速度尺、左右分段弧形括号及水平短线、ALT 高度尺、底部横条和角落小方框。按参考截图用程序绘制，不包含游戏背景、角色状态或水印。

支持**先单独生成透明 mask，再用 FFmpeg 叠加**。Mask 使用 `.mov` 的 QuickTime Animation (`qtrle`, `argb`) 编码保留透明度；普通 H.264 MP4 无法保留这个透明通道。部分播放器会把透明背景显示为黑色，叠加时仍然透明。

## 安装与运行

需要 Python 3.13+、uv、FFmpeg/ffprobe（加入 PATH）。

```powershell
uv sync
uv run bird-dji --help
```

### 单独导出 mask

```powershell
uv run bird-dji mask --video videos/DJI_20261002102503_0016_D.MP4 --srt videos/DJI_20261002102503_0016_D.SRT -o outputs/drone_mask.mov
```

提供 `--video` 自动匹配画面尺寸、帧率及片长。仅有 SRT 也能生成：

```powershell
uv run bird-dji mask --srt videos/DJI_20261002102503_0016_D.SRT --width 3840 --height 2160 --fps 30000/1001 -o outputs/drone_mask.mov
```

### 合成已有 mask

```powershell
uv run bird-dji overlay --video videos/DJI_20261002102503_0016_D.MP4 --mask outputs/drone_mask.mov -o outputs/drone_hud.mp4
```

也可以直接调用 FFmpeg（mask 与视频需同尺寸、同起点）：

```powershell
ffmpeg -i videos/DJI_20261002102503_0016_D.MP4 -i outputs/drone_mask.mov -filter_complex "[0:v][1:v]overlay=0:0:format=auto:alpha=straight[v]" -map "[v]" -map "0:a?" -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -c:a copy -movflags +faststart outputs/drone_hud.mp4
```

### 自动处理

```powershell
# 一条命令生成 mask 并导出合成视频（保留 mask）
uv run bird-dji render --video videos/DJI_20261002102503_0016_D.MP4 --srt videos/DJI_20261002102503_0016_D.SRT -o outputs/drone_hud.mp4

# 批量配对目录内同名视频和 SRT，不区分扩展名大小写
uv run bird-dji batch videos --output-dir outputs

# 单帧透明 PNG 预览
uv run bird-dji preview --video videos/DJI_20261002102503_0016_D.MP4 --srt videos/DJI_20261002102503_0016_D.SRT --time 4 -o outputs/hud.png
```

可选参数：`--duration 3` 只导出前三秒；`--line-width 5` 增加线宽（默认 4，以 1080p 为基准，随分辨率缩放）；`--opacity 0.9` 增强白线（默认 0.85）；`--hud-scale 0.55` 缩小 HUD（默认 0.65，允许 0.5–1，整体居中，文字和线条保持可读）；`--reticle fixed` 固定圆圈；`--width 1920 --height 1080` 用较小 mask 合成原尺寸视频；`--window 1` 控制 GPS 估算窗口；`--offset 0.5` 将视频 t 秒对齐 SRT t+0.5 秒；`--overwrite` 替换已有输出。合成默认 CPU `libx264`，有支持 NVIDIA 编码的显卡时可以加 `--encoder h264_nvenc`。合成保留原视频尺寸、时间顺序和可复制的原音轨。输出为兼容性较好的 8-bit H.264，会重新编码视频；目前不保留源片的 10-bit 位深、DJI 私有数据流或 HDR 元数据。

## 人体关键点方块（YOLOv8）

安装可选依赖并把官方 `yolov8n-pose.pt` 放到 `models/`（可用 `--pose-model` 指定其他 YOLOv8 pose 权重）：

```powershell
uv sync --extra pose
uv run --extra pose bird-dji batch videos --output-dir outputs --pose --encoder h264_nvenc --overwrite
```

`--pose` 同样适用于 `mask`、`render` 和 `preview`。人体关键点直接绘入透明 mask，偏红的橙色小方框内带中心菱形，不画骨架、不画人体包围框。默认按视频时间每秒检测 10 次（0、0.1、0.2…秒），以该时刻附近的视频帧为输入；两次扫描之间保持上次坐标，下一次扫描覆盖，检测消失就清除。保存旁边的 `.pose.json` 可查看扫描时间、人数、归一化关键点坐标与置信度。离线推理和导出速度取决于硬件。

默认 `--pose-confidence 0.5` 过滤低可信和遮挡的关键点；`--pose-interval 0.1` 为扫描间隔，可改为 `1` 恢复每秒一次；`--pose-device cpu` 可改成 `0` 使用 CUDA（需安装支持 CUDA 的 PyTorch）。模型在本地运行，视频不会上传。关键点推理输入尺寸默认 `--pose-imgsz 960`，可调为 `1280` 提高细节识别。坐标按完整视频画面映射，不随中央 HUD 缩小。

官方模型与关键点 API：[YOLOv8 模型](https://docs.ultralytics.com/models/yolov8/)、[Keypoints](https://docs.ultralytics.com/reference/engine/results/#ultralytics.engine.results.Keypoints)。

## 自毁模式与释放蜂鸟提示

默认在导出视频最后 3 秒进入自毁模式：约 0.12 秒内快速切换为红色 HUD，括号和刻度变细变淡，速度填充线、水平短线和生命值填充条保持鲜明的红色，瞄准圆圈及连接线进一步淡化。红色警告牌内有黑色警告三角与“自毁模式”。保留实拍画面，不做末尾黑屏或断信号效果。`--self-destruct-last 5` 改为最后 5 秒；`--self-destruct-at 6` 指定从第 6 秒开始（优先于末尾秒数）；`--no-self-destruct` 关闭。短于 3 秒的片段从开头进入过渡。红橙色人体关键点保持原样。

开启 `--pose` 后，选择画面中 bbox 中心距离移动瞄准圆圈最近的人，显示 `X 释放蜂鸟`（按屏幕像素距离选择）。提示第一次出现时，其整体中心放在 bbox 中心；随后按 0.2 秒平滑响应跟随，并限制最大速度为 1080p 下 180 像素/秒（随分辨率缩放），不瞬间跳到新位置。人物框默认每秒刷新 10 次，按相邻扫描 bbox 的重叠率关联；未检测到人物时隐藏，切换人物时重新居中。这里只绘制视频 UI，不绑定按键或实际无人机动作。

用 `--release-follow-speed 100` 降低移动速度，`--no-release-prompt` 关闭提示。`.pose.json` 保存归一化 bbox 和临时跟踪编号，`.release.json` 保存触发时刻与初始位置，方便检查。bbox 只用于判定，不画出来。

自毁阶段合成时还会给实拍背景加入轻微红蓝色差和暗角，HUD 保持清楚，不添加黑屏。Mask 旁边的 `.hud.json` 保存开始时间，使用 `bird-dji overlay` 时会自动读取。透明 mask 自身包含红色 UI，背景色差/暗角须在合成阶段应用；直接使用普通 FFmpeg overlay 示例只叠 UI。移动 mask 时一并保留同名 `.hud.json`。

## 遥测的含义

- 底部横条为模拟无人机生命值：按本次导出片长线性递减，第一帧满格、最后一帧空格；白色填充从两侧对称向中心缩短，空槽保留淡色底轨。这不是飞控真实电量或生命值读数，SRT offset 不影响其进度。`--duration` 截短时使用截短后的片长。

- `rel_alt` 用于 ALT，单位米；缺失显示 `--`。高度尺视觉范围 0–100 米，数值不截断。
- 优先读取 `h_speed` / `hspeed` / `horizontal_speed`，假定单位 m/s；没有这些字段时用 GPS 在默认一秒窗口内的位移估算**水平地速**。先统计整份 SRT 的最高速度，再按 `当前速度 / 最高速度` 映射 SPD 尺；最高速度对应满格，零速度对应底部，整段零速度时安全显示空条。每段独立统计，即使 `--duration` 截短输出，也使用完整 SRT 的峰值。数字仍是实际 m/s，保留一位小数。
- 优先读取 `yaw` / `heading` / `flight_yaw`，假定单位度；没有朝向字段时显示 **GPS 航迹方向**，它与机头/相机朝向可能不同。窗口位移不足 0.5 米或速度不足 0.5 m/s 时显示 `--`，避免悬停时随机跳方向。
- 有视频时，顶部方向条从视频起点的 0° 开始，根据全局画面横向位移累计滑动，只显示带正负号的相对角度，不显示说明文字。停止转镜头后方向条保持累计位置，不随圆圈回中而复位。这是游戏化的视觉方向（整屏横移映射为 180°），未标定真实相机视角，也不代表地理方位。
- 仅有 SRT 时，顶部使用字幕朝向或 GPS 航迹；有有效绝对方向数据才显示北/东/南/西，方向未知显示 `--`。跨越 359°→0° 按最短方向插值；Windows 使用微软雅黑，其他环境回退英文方向。`--reticle fixed` 只固定圆圈，有视频时顶部仍随镜头滑动。
- 左右括号和刻度固定居中，整体缩至原布局的 65%。有视频时中心圆圈用 OpenCV 稀疏光流和 RANSAC 的全局画面位移估计转镜头方向，并平滑、限幅，在停止转镜头后渐渐回中。移动人物的局部运动尽量通过全局拟合排除。
- 圆圈运动是**视觉效果估计**，不是云台角度读数：画面平移也可能来自无人机移动，无法仅凭图像区分。弱纹理、遮挡或剧烈跳切时不采用不可靠位移。仅提供 SRT 时无法推断镜头方向，圆圈固定居中。不会用 GPS 航迹假装相机朝向，也不会根据 GPS 推断画面倾斜。
- 字幕时间轴为准，缺失/结束后的数据不会无限沿用。GPS 是估算数据，不是飞控速度读数，短视频边缘使用可用的单侧窗口。

当前 `videos` 内两组 DJI 素材仅含 GPS 和高度，速度与方向按上述方法估算。默认一秒估算窗口下，0015 的峰值约 0.562 m/s，0016 约 0.149 m/s；这些是各自的满格值，GPS 精度可能影响低速读数。

## 验证

中心圆圈默认采用更明显的游戏控制视角效果：转镜头响应增益为 12（初版为 4），最大偏移可达到 HUD 宽/高的 18%（初版为 7.5%），响应较快、回中较慢。偏移时有一条从屏幕正中心连到圆圈近侧边缘的白线，圆圈回到中心附近时连接线消失，圆圈内部保持空心。在默认 65% HUD 下，1080p 的水平/垂直偏移上限约为 225/126 像素。可用 `--reticle-gain 16 --reticle-range 0.22` 继续增强；范围最大 0.25。这个运动效果仍根据画面运动估计，不代表真实云台姿态。

```powershell
uv run python -m unittest discover -s tests -v
```

输出先写入临时目录，完成后才成为正式文件；不会覆盖输入视频。`videos/` 和 `outputs/` 已加入 Git 忽略。
