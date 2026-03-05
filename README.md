# 📦 图片工具箱插件

一个功能强大的 AstrBot 图片处理和管理插件，基于 LunaBot 的图片工具功能开发。

## 🎯 核心功能

### 图片处理功能
- **缩放**：调整图片大小
- **旋转**：旋转图片角度
- **镜像**：水平或垂直翻转图片
- **灰度**：将图片转换为灰度图
- **反转**：颜色反转
- **亮度**：调整图片亮度
- **对比度**：调整图片对比度
- **模糊**：高斯模糊效果

### 画廊管理功能
- **创建画廊**：创建新的图片画廊
- **删除画廊**：删除现有的图片画廊
- **上传图片**：将图片上传到指定画廊
- **删除图片**：从画廊中删除指定图片
- **查看图片**：从画廊中随机查看图片
- **列出画廊**：查看所有可用的画廊
- **图片去重**：自动检测重复图片
- **缩略图生成**：为图片生成缩略图

## 🚀 安装方法

### 方法一：通过插件管理
1. 在 AstrBot 插件管理中搜索并安装 `astrbot_plugin_imgtool`

### 方法二：手动安装
1. 将 `astrbot_plugin_imgtool` 目录复制到 AstrBot 的插件目录
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 重启 AstrBot

## 📋 依赖项
- **Pillow**：图像处理库
- **numpy**：数值计算库
- **aiohttp**：异步HTTP客户端
- **playwright**：网页截图库（用于截图画廊图片）
- **nonebot2[fastapi]**：NoneBot2框架
- **nonebot-adapter-onebot**：OneBot协议适配器
- **nonebot_plugin_htmlrender**：HTML渲染插件
- **nonebot_plugin_picstatus**：图片状态插件
- **nonebot_plugin_apscheduler**：定时任务调度器
- **tenacity**：网络请求重试库
- **matplotlib**：数据可视化库
- **jieba**：中文分词库
- **requests**：HTTP请求库
- **openai**：OpenAI API客户端
- **pandas**：数据处理库
- **httpx**：现代HTTP客户端
- **wordcloud**：词云生成库
- **ascii_magic**：ASCII艺术生成库
- **PicImageSearch**：图片搜索库
- **imageio[ffmpeg]**：图像和视频处理库
- **opencv-python**：计算机视觉库
- **scipy**：科学计算库
- **ffmpeg-python**：FFmpeg包装库
- **pdf2image**：PDF转图像库
- **colour-science**：色彩科学库
- **rapidfuzz**：模糊字符串匹配库

## 🎮 使用方法

### 图片处理命令
- **查看可用操作**：`img`
- **执行图片操作**：`img 操作1 参数1 操作2 参数2 ...`
- **查看操作帮助**：`img help 操作名`

### 画廊管理命令
- **创建画廊**：`gall open 画廊名称`
- **删除画廊**：`gall close 画廊名称`
- **上传图片**：`gall add 画廊名称`（需要附带图片）
- **删除图片**：`gall del 图片ID1 图片ID2 ...`
- **查看图片**：`gall pick 画廊名称 [数量]`
- **列出画廊**：`gall list`

### 示例用法
1. **缩放图片**：`img resize 500` - 将图片缩放到长边为500像素
2. **旋转图片**：`img rotate 90` - 逆时针旋转90度
3. **创建画廊**：`gall open 表情包`
4. **上传图片**：发送 `gall add 表情包` 并附带要上传的图片
5. **查看图片**：`gall pick 表情包 3` - 从表情包画廊中随机查看3张图片

## 📁 插件结构

```
astrbot_plugin_imgtool/
├── __init__.py          # 插件入口
├── gallery.py           # 画廊功能实现
├── main.py              # 核心功能实现
├── metadata.yaml        # 插件元数据
└── requirements.txt     # 依赖项
```

## 🌟 特点

- **功能丰富**：提供多种图片处理操作和完整的画廊管理功能
- **易于使用**：简洁的命令格式和详细的帮助信息
- **智能去重**：自动检测重复图片，避免画廊中出现重复内容
- **性能优化**：生成缩略图，提高图片浏览速度
- **数据安全**：自动保存画廊数据，确保内容不会丢失
- **支持动图**：可以处理静态图和动图
- **智能截图**：使用 playwright 对画廊图片进行截图，确保图片显示正常

## 📞 支持

如果在使用过程中遇到任何问题，请：
1. 检查插件的日志输出
2. 确保所有依赖项已正确安装
3. 确认 AstrBot 版本 >= 4.10.4

## 📄 许可证

本项目基于 MIT 许可证开源。

---

** Enjoy your image processing and management! ** 🎨