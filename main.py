import asyncio
import os
import sys
import random
from pathlib import Path
from typing import Any, List, Union

from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import (
    EventMessageType,
    PermissionType,
    PlatformAdapterType,
)
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Image as ImageComponent
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star

from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from enum import Enum
import numpy as np

from .gallery import GalleryManager, GalleryMode, GalleryPicRepeatedException


class ImageType(Enum):
    Any         = 1
    Animated    = 2
    Static      = 3
    Multiple    = 4

    def __str__(self):
        if self == ImageType.Any:
            return "任意单图"
        elif self == ImageType.Animated:
            return "动图"
        elif self == ImageType.Static:
            return "静态图"
        elif self == ImageType.Multiple:
            return "多张图片"

    def check_img(self, img) -> bool:
        if self == ImageType.Multiple:
            if not isinstance(img, list):
                return False
            for i in img:
                if not isinstance(i, Image.Image):
                    return False
                if self._is_animated(i):
                    return False
                return True
        elif self == ImageType.Any:
            return True
        elif self == ImageType.Animated:
            return self._is_animated(img)
        elif self == ImageType.Static:
            return not self._is_animated(img)

    def check_type(self, tar) -> bool:
        if self == ImageType.Multiple:
            return self == tar
        if self == ImageType.Any or tar == ImageType.Any:
            return True
        return self == tar

    @classmethod
    def get_type(cls, img) -> 'ImageType':
        if isinstance(img, list):
            return ImageType.Multiple
        elif cls._is_animated(img):
            return ImageType.Animated
        else:
            return ImageType.Static
    
    @staticmethod
    def _is_animated(img):
        return getattr(img, 'n_frames', 1) > 1


class ImageOperation:
    all_ops = {}

    def __init__(self, name: str, input_type: ImageType, output_type: ImageType, process_type: str='batch'):
        self.name = name
        self.input_type = input_type
        self.output_type = output_type
        self.process_type = process_type
        self.help = ""
        self.input_limit = 1024 * 1024 * 16  # 16MP
        ImageOperation.all_ops[name] = self
        assert process_type in ['single', 'batch'], f"图片操作类型{process_type}错误"
        assert not (input_type == ImageType.Multiple and process_type == 'batch'), f"多张图片操作不能以批量方式处理"

    def parse_args(self, args: List[str]) -> dict:
        return None

    def operate(self, img: Image.Image, args: dict=None, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        raise NotImplementedError()

    def __call__(self, img: Image.Image, args: List[str]) -> Image.Image:
        try:
            args = self.parse_args(args)
        except Exception as e:
            if str(e):
                msg = f"参数错误: {e}\n{self.help}"
            else:
                msg = f"参数错误\n{self.help}"
            raise Exception(msg.strip())
        
        def apply_limit(img: Union[Image.Image, List[Image.Image]]):
            if isinstance(img, Image.Image) and not ImageType._is_animated(img):
                w, h = img.size
                img = self._limit_image_by_pixels(img, self.input_limit)
                new_w, new_h = img.size
                if (w, h) != (new_w, new_h):
                    logger.info(f"图片操作 {self.name} 对超限输入进行缩放 {w}x{h} -> {new_w}x{new_h}")
            else:
                is_single_gif = False
                if isinstance(img, Image.Image):
                    is_single_gif = True
                    duration = self._get_gif_duration(img)
                    img = self._gif_to_frames(img)
                
                w, h, n = img[0].size[0], img[0].size[1], len(img)
                img = self._limit_image_by_pixels(img, self.input_limit)
                new_w, new_h, new_n = img[0].size[0], img[0].size[1], len(img)

                if (n, w, h) != (new_n, new_w, new_h):
                    logger.info(f"图片操作 {self.name} 对超限输入进行缩放 {n}x{w}x{h} -> {new_n}x{new_w}x{new_h}")
                if is_single_gif:
                    img = self._frames_to_gif(img, int(duration * new_n / n))
            return img

        def process_image(img):
            img_type = ImageType.get_type(img)
            if self.process_type == 'single':
                return self.operate(apply_limit(img), args)
            elif self.process_type == 'batch':
                if img_type == ImageType.Animated:
                    frames = self._gif_to_frames(img)
                    frames = apply_limit(frames)
                    frames = [self.operate(f, args, img_type, i, img.n_frames) for i, f in enumerate(frames)]
                    return self._frames_to_gif(frames, self._get_gif_duration(img))
                else:
                    return self.operate(apply_limit(img), args, img_type)
        
        img_type = ImageType.get_type(img)
        logger.info(f"执行图片操作:{self.name} 输入类型:{img_type} 参数:{args}")
        if self.input_type != ImageType.Multiple and img_type == ImageType.Multiple:
            logger.info(f"为 {self.name} 操作批量处理 {len(img)} 张图片")
            return [process_image(i) for i in img]
        else:
            return process_image(img)
    
    def _limit_image_by_pixels(self, img, max_pixels):
        if isinstance(img, list):
            return [self._limit_image_by_pixels(i, max_pixels) for i in img]
        w, h = img.size
        if w * h <= max_pixels:
            return img
        scale = (max_pixels / (w * h)) ** 0.5
        new_w = int(w * scale)
        new_h = int(h * scale)
        return img.resize((new_w, new_h), Image.Resampling.BILINEAR)
    
    def _is_animated(self, img):
        return ImageType._is_animated(img)
    
    def _get_gif_duration(self, img):
        return img.info.get('duration', 100)
    
    def _gif_to_frames(self, img):
        frames = []
        try:
            for i in range(img.n_frames):
                img.seek(i)
                frames.append(img.copy())
        except Exception:
            frames = [img]
        return frames
    
    def _frames_to_gif(self, frames, duration):
        from io import BytesIO
        buffer = BytesIO()
        frames[0].save(buffer, format='GIF', save_all=True, append_images=frames[1:], duration=duration, loop=0)
        buffer.seek(0)
        return Image.open(buffer)


class ResizeOperation(ImageOperation):
    def __init__(self):
        super().__init__("resize", ImageType.Any, ImageType.Any, 'batch')
        self.help = """
缩放图像，使用方式:
resize 256 128: 缩放到256x128
resize 256: 保持宽高比缩放到长边为256
resize 0.5x: 保持宽高比缩放到原图50%
resize 3.0x 2.0x: 宽缩放3倍高缩放2倍
""".strip()

    def parse_args(self, args: List[str]) -> dict:
        ret = {
            'w_scale': None,
            'h_scale': None,
            'w': None,
            'h': None,
            'max': None,
        }
        if len(args) == 1:
            if args[0].endswith('x'):
                ret['w_scale'] = float(args[0].removesuffix('x'))
                ret['h_scale'] = float(args[0].removesuffix('x'))
            else:
                ret['max'] = int(args[0])
        elif len(args) == 2:
            if args[0].endswith('x'):
                ret['w_scale'] = float(args[0].removesuffix('x'))
            else:
                ret['w'] = int(args[0])
            if args[1].endswith('x'):
                ret['h_scale'] = float(args[1].removesuffix('x'))
            else:
                ret['h'] = int(args[1])
        else:
            raise Exception()
        return ret

    def operate(self, img: Image.Image, args: dict, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        w, h = img.size
        if args['max'] is not None:
            if w > h:
                h = int(args['max'] * h / w)
                w = args['max']
            else:
                w = int(args['max'] * w / h)
                h = args['max']
        else:
            if args['w_scale'] is not None:
                w = int(w * args['w_scale'])
            if args['h_scale'] is not None:
                h = int(h * args['h_scale'])
            if args['w'] is not None:
                w = args['w']
            if args['h']is not None:
                h = args['h']
        assert 0 < w * h * total_frame <= 1024 * 1024 * 16, f"图片尺寸{w}x{h}超出限制"
        return img.resize((w, h), Image.Resampling.BILINEAR)


class MirrorOperation(ImageOperation):
    def __init__(self):
        super().__init__("mirror", ImageType.Any, ImageType.Any, 'batch')
        self.help = """
镜像翻转，使用方式:
mirror: 水平镜像
mirror v: 垂直镜像
""".strip()
        
    def parse_args(self, args: List[str]) -> dict:
        args = [arg[0].lower() for arg in args]
        assert len(args) <= 1, "最多只支持一个参数"
        if 'v' in args:
            return {'mode': 'v'}
        return {'mode': 'h'}
    
    def operate(self, img: Image.Image, args: dict, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        if args['mode'] == 'h':
            return img.transpose(Image.FLIP_LEFT_RIGHT)
        else:
            return img.transpose(Image.FLIP_TOP_BOTTOM)


class RotateOperation(ImageOperation):
    def __init__(self):
        super().__init__("rotate", ImageType.Any, ImageType.Any, 'batch')
        self.help = """
旋转图像，使用方式:
rotate 90: 逆时针旋转90度
""".strip()
        
    def parse_args(self, args: List[str]) -> dict:
        assert len(args) == 1, "需要一个角度参数"
        return {'degree': int(args[0])}
    
    def operate(self, img: Image.Image, args: dict, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        return img.rotate(args['degree'], expand=True)


class GrayOperation(ImageOperation):
    def __init__(self):
        super().__init__("gray", ImageType.Any, ImageType.Any, 'batch')
        self.help = "将图片转换为灰度图"
    
    def parse_args(self, args: List[str]) -> dict:
        assert not args, "该操作不接受参数"
        return None
    
    def operate(self, img: Image.Image, args: dict=None, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        return img.convert('L')


class InvertOperation(ImageOperation):
    def __init__(self):
        super().__init__("invert", ImageType.Any, ImageType.Any, 'batch')
        self.help = "将图片颜色反转"

    def parse_args(self, args: List[str]) -> dict:
        assert not args, "该操作不接受参数"
        return None

    def operate(self, img: Image.Image, args: dict=None, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        img = img.convert('RGB')
        return ImageOps.invert(img)


class BrightenOperation(ImageOperation):
    def __init__(self):
        super().__init__("brighten", ImageType.Any, ImageType.Any, 'batch')
        self.help = """
调整图片亮度，使用方式:
brighten 1.5: 调整图片亮度为1.5倍
brighten 0.5: 调整图片亮度为0.5倍
0.0对应黑色图像，1.0对应原图像
""".strip()
        
    def parse_args(self, args: List[str]) -> dict:
        assert len(args) == 1, "需要一个参数"
        ret = {'ratio': float(args[0])}
        assert 0.0 <= ret['ratio'] <= 100.0, "亮度参数只能在0.0-100.0之间"
        return ret  
    
    def operate(self, img: Image.Image, args: dict, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        ratio = args['ratio']
        img = img.convert('RGBA')
        return ImageEnhance.Brightness(img).enhance(ratio)
    

class ContrastOperation(ImageOperation):
    def __init__(self):
        super().__init__("contrast", ImageType.Any, ImageType.Any, 'batch')
        self.help = """
调整图片对比度，使用方式:
contrast 1.5: 调整图片对比度为1.5倍
contrast 0.5: 调整图片对比度为0.5倍
0.0对应纯灰图像，1.0对应原图像
""".strip()
        
    def parse_args(self, args: List[str]) -> dict:
        assert len(args) == 1, "需要一个参数"
        ret = {'ratio': float(args[0])}
        assert 0.0 <= ret['ratio'] <= 100.0, "对比度参数只能在0.0-100.0之间"
        return ret  
    
    def operate(self, img: Image.Image, args: dict, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        ratio = args['ratio']
        img = img.convert('RGBA')
        return ImageEnhance.Contrast(img).enhance(ratio)


class BlurOperation(ImageOperation):
    def __init__(self):
        super().__init__("blur", ImageType.Any, ImageType.Any, 'batch')
        self.help = """
对图片进行模糊处理，使用方式:
blur 对图片应用默认半径为3的高斯模糊
blur 5 对图片应用半径为5的高斯模糊
""".strip()

    def parse_args(self, args: List[str]) -> dict:
        assert len(args) <= 1, "最多只支持一个参数"
        ret = {'radius': 3}
        if args:
            ret['radius'] = int(args[0])
        assert 1 <= ret['radius'] <= 32, "模糊半径只能在1-32之间"
        return ret
    
    def operate(self, img: Image.Image, args: dict, image_type: ImageType=None, frame_idx: int=0, total_frame: int=1) -> Image.Image:
        radius = args['radius']
        img = img.convert('RGBA')
        return img.filter(ImageFilter.GaussianBlur(radius=radius))


# 初始化图片操作
ResizeOperation()
MirrorOperation()
RotateOperation()
GrayOperation()
InvertOperation()
BrightenOperation()
ContrastOperation()
BlurOperation()


class Main(Star):
    """图片工具箱插件

    功能：
    - 提供多种图片处理操作，如缩放、旋转、镜像、滤镜等
    - 支持处理静态图和动图
    - 提供简洁的命令接口
    """

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        
        # 初始化插件配置
        self.base_dir = Path(__file__).parent
        # 使用官方推荐的插件数据目录
        astrbot_data_path = get_astrbot_data_path()
        # 确保使用Path对象
        if isinstance(astrbot_data_path, str):
            astrbot_data_path = Path(astrbot_data_path)
        plugin_data_path = astrbot_data_path / "plugin_data" / self.name
        self.data_dir = plugin_data_path
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化画廊管理器
        self.gallery_manager = GalleryManager.get(self.data_dir)
        
        # 运行时属性
        self.image_list = {}
        self.image_list_edit_time = {}
        self.IMAGE_LIST_CLEAN_INTERVAL_SECONDS = 3600  # 1小时
        self.MULTI_IMAGE_MAX_NUM = 10

    async def initialize(self):
        """初始化插件"""
        logger.info("图片工具箱插件初始化完成")

    async def terminate(self):
        """终止插件"""
        logger.info("图片工具箱插件已终止")

    async def _download_image(self, url):
        """下载图片"""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    from io import BytesIO
                    data = await response.read()
                    return Image.open(BytesIO(data))
                else:
                    raise Exception(f"下载图片失败: {response.status}")

    async def _get_image_from_event(self, event: AstrMessageEvent):
        """从事件中获取图片"""
        images = []
        for component in event.get_messages():
            if isinstance(component, ImageComponent):
                try:
                    img = await self._download_image(component.url)
                    images.append(img)
                except Exception as e:
                    logger.error(f"获取图片失败: {e}")
        if not images:
            raise Exception("未找到图片")
        if len(images) == 1:
            return images[0]
        return images

    async def _send_image(self, event: AstrMessageEvent, img: Image.Image):
        """发送图片"""
        from io import BytesIO
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        # 这里需要根据AstrBot的API来发送图片
        # 暂时使用简单的方式
        await event.reply(ImageComponent(buffer.getvalue()))

    async def _operate_image(self, event: AstrMessageEvent, args: List[str]):
        """执行图片操作"""
        # 获取图片
        img = await self._get_image_from_event(event)
        
        # 解析操作序列
        ops = []
        current_op = None
        current_args = []
        
        for arg in args:
            if arg in ImageOperation.all_ops:
                if current_op:
                    ops.append((current_op, current_args))
                current_op = ImageOperation.all_ops[arg]
                current_args = []
            else:
                if not current_op:
                    raise Exception(f"未指定初始操作, 可用的操作: {', '.join(ImageOperation.all_ops.keys())}")
                current_args.append(arg)
        
        if current_op:
            ops.append((current_op, current_args))
        
        if not ops:
            raise Exception(f"未指定操作, 可用的操作: {', '.join(ImageOperation.all_ops.keys())}")
        
        if len(ops) > 10:
            raise Exception("操作过多, 最多支持10个操作")
        
        # 检查操作输入输出类型是否对应
        for i in range(1, len(ops)):
            pre_type = ops[i-1][0].output_type
            cur_type = ops[i][0].input_type
            if not pre_type.check_type(cur_type):
                raise Exception(f"第{i}个操作 {ops[i-1][0].name} 的输出类型 {pre_type} 与 第{i+1}个操作 {ops[i][0].name} 的输入类型 {cur_type} 不匹配")
        
        # 检查初始输入类型是否匹配
        img_type = ImageType.get_type(img)
        first_input_type = ops[0][0].input_type
        if isinstance(img, list):
            if first_input_type != ImageType.Multiple:
                for i, item in enumerate(img):
                    if not first_input_type.check_img(item):
                        raise Exception(f"第{i+1}张图片类型不匹配, 需要 {first_input_type}, 实际为 {ImageType.get_type(item)}")
        else:
            if not first_input_type.check_img(img):
                raise Exception(f"初始图片类型不匹配, 需要 {first_input_type}, 实际为 {img_type}")
        
        # 执行操作序列
        result = img
        for i, (op, op_args) in enumerate(ops):
            try:
                result = op(result, op_args)
            except Exception as e:
                raise Exception(f"执行第{i+1}个图片操作 {op.name} 失败: {e}")
        
        # 发送结果
        if isinstance(result, list):
            for i, item in enumerate(result):
                await self._send_image(event, item)
        else:
            await self._send_image(event, result)

    @filter.command("/img")
    async def img_command(self, event: AstrMessageEvent):
        """图片操作命令
        用法: /img 操作1 参数1 操作2 参数2 ...
        可用的操作: resize, mirror, rotate, gray, invert, brighten, contrast, blur
        """
        try:
            args = event.get_message_str().strip().split()[1:]  # 去掉 /img
            if not args:
                await event.send(MessageChain([Plain(f"请指定操作，可用的操作: {', '.join(ImageOperation.all_ops.keys())}")]))
                return
            
            await self._operate_image(event, args)
        except Exception as e:
            await event.send(MessageChain([Plain(f"操作失败: {e}")]))

    @filter.command("/img help")
    async def img_help(self, event: AstrMessageEvent):
        """查看图片操作帮助"""
        args = event.get_message_str().strip().split()[2:]  # 去掉 /img help
        if not args:
            await event.send(MessageChain([Plain(f"可用的操作: {', '.join(ImageOperation.all_ops.keys())}\n使用 /img help 操作名 获取详细帮助")]))
            return
        
        op_name = args[0]
        if op_name not in ImageOperation.all_ops:
            await event.send(MessageChain([Plain(f"未找到操作 {op_name}, 可用的操作: {', '.join(ImageOperation.all_ops.keys())}")]))
            return
        
        op = ImageOperation.all_ops[op_name]
        msg = f"【{op.name}】\n"
        msg += f"{op.input_type} -> {op.output_type}\n"
        msg += op.help
        await event.send(MessageChain([Plain(msg)]))

    # ==================== 画廊功能 ====================

    @filter.command("/gall open")
    async def gall_open(self, event: AstrMessageEvent):
        """创建一个新画廊"""
        try:
            args = event.get_message_str().strip().split()[2:]  # 去掉 /gall open
            if not args:
                await event.send(MessageChain([Plain("使用方式: /gall open 画廊名称")]))
                return
            name = ' '.join(args)
            self.gallery_manager.open_gall(name)
            await event.send(MessageChain([Plain(f'画廊"{name}"创建成功')]))
        except Exception as e:
            await event.send(MessageChain([Plain(f'创建画廊失败: {e}')]))

    @filter.command("/gall close")
    async def gall_close(self, event: AstrMessageEvent):
        """删除一个画廊"""
        try:
            args = event.get_message_str().strip().split()[2:]  # 去掉 /gall close
            if not args:
                await event.send(MessageChain([Plain("使用方式: /gall close 画廊名称")]))
                return
            name = ' '.join(args)
            self.gallery_manager.close_gall(name)
            await event.send(MessageChain([Plain(f'画廊"{name}"删除成功')]))
        except Exception as e:
            await event.send(MessageChain([Plain(f'删除画廊失败: {e}')]))

    @filter.command("/gall add")
    async def gall_add(self, event: AstrMessageEvent):
        """上传图片到画廊"""
        try:
            args = event.get_message_str().strip().split()[2:]  # 去掉 /gall add
            if not args:
                await event.send(MessageChain([Plain("使用方式: /gall add 画廊名称")]))
                return
            name = ' '.join(args)
            
            # 获取图片
            images = []
            for component in event.get_messages():
                if isinstance(component, ImageComponent):
                    try:
                        img = await self._download_image(component.url)
                        images.append(img)
                    except Exception as e:
                        logger.error(f"获取图片失败: {e}")
            if not images:
                await event.send(MessageChain([Plain("未找到图片")]))
                return
            
            # 保存图片并添加到画廊
            ok_list = []
            err_list = []
            for i, img in enumerate(images):
                try:
                    # 保存临时文件
                    from io import BytesIO
                    buffer = BytesIO()
                    img.save(buffer, format='PNG')
                    buffer.seek(0)
                    
                    # 保存到临时文件
                    temp_path = str(self.data_dir / f"temp_{i}.png")
                    with open(temp_path, 'wb') as f:
                        f.write(buffer.getvalue())
                    
                    # 添加到画廊
                    pid = await self.gallery_manager.async_add_pic(name, temp_path)
                    ok_list.append(pid)
                    
                    # 删除临时文件
                    os.remove(temp_path)
                except GalleryPicRepeatedException as e:
                    err_list.append(f"第{i+1}张图片与已有图片重复(pid={e.pid})")
                except Exception as e:
                    err_list.append(f"第{i+1}张图片上传失败: {e}")
            
            # 发送结果
            msg = f"成功上传{len(ok_list)}/{len(images)}张图片到\"{name}\"\n"
            if ok_list:
                msg += f"成功的图片ID: {', '.join(map(str, ok_list))}\n"
            if err_list:
                msg += "\n".join(err_list)
            await event.send(MessageChain([Plain(msg)]))
        except Exception as e:
            await event.send(MessageChain([Plain(f'上传图片失败: {e}')]))

    @filter.command("/gall del")
    async def gall_del(self, event: AstrMessageEvent):
        """删除画廊中的图片"""
        try:
            args = event.get_message_str().strip().split()[2:]  # 去掉 /gall del
            if not args:
                await event.send(MessageChain([Plain("使用方式: /gall del 图片ID1 图片ID2 ...")]))
                return
            
            pids = []
            for arg in args:
                try:
                    pids.append(int(arg))
                except:
                    await event.send(MessageChain([Plain(f'无效的图片ID: {arg}')]))
                    return
            
            ok_list = []
            err_list = []
            for pid in pids:
                try:
                    self.gallery_manager.del_pic(pid)
                    ok_list.append(pid)
                except Exception as e:
                    err_list.append(f"删除图片ID {pid}失败: {e}")
            
            msg = f"成功删除{len(ok_list)}/{len(pids)}张图片\n"
            if ok_list:
                msg += f"成功删除的图片ID: {', '.join(map(str, ok_list))}\n"
            if err_list:
                msg += "\n".join(err_list)
            await event.send(MessageChain([Plain(msg)]))
        except Exception as e:
            await event.send(MessageChain([Plain(f'删除图片失败: {e}')]))

    @filter.command("/gall pick")
    async def gall_pick(self, event: AstrMessageEvent):
        """查看画廊中的图片"""
        try:
            args = event.get_message_str().strip().split()[2:]  # 去掉 /gall pick
            if not args:
                await event.send(MessageChain([Plain("使用方式: /gall pick 画廊名称 [数量]")]))
                return
            
            name = args[0]
            num = 1
            if len(args) > 1:
                try:
                    num = int(args[1])
                    if num < 1 or num > 10:
                        await event.send(MessageChain([Plain("数量必须在1-10之间")]))
                        return
                except:
                    await event.send(MessageChain([Plain("无效的数量")]))
                    return
            
            # 查找画廊
            gallery = self.gallery_manager.find_gall(name, raise_if_nofound=True)
            
            # 检查画廊模式
            if gallery.mode == GalleryMode.Off:
                await event.send(MessageChain([Plain(f'画廊"{name}"已关闭')]))
                return
            
            # 检查画廊是否有图片
            if not gallery.pics:
                await event.send(MessageChain([Plain(f'画廊"{name}"没有图片')]))
                return
            
            # 随机选择图片
            if len(gallery.pics) < num:
                num = len(gallery.pics)
            selected_pics = random.sample(gallery.pics, num)
            
            # 发送图片
            for pic in selected_pics:
                try:
                    if os.path.exists(pic.path):
                        with open(pic.path, 'rb') as f:
                            await event.send(MessageChain([ImageComponent(f.read())]))
                except Exception as e:
                    logger.error(f"发送图片失败: {e}")
        except Exception as e:
            await event.send(MessageChain([Plain(f'查看图片失败: {e}')]))

    @filter.command("/gall list")
    async def gall_list(self, event: AstrMessageEvent):
        """列出所有画廊"""
        try:
            galleries = self.gallery_manager.get_all_galls()
            if not galleries:
                await event.send(MessageChain([Plain('当前没有任何画廊')]))
                return
            
            msg = "画廊列表:\n"
            for name, gallery in galleries.items():
                msg += f"- {name} (模式: {gallery.mode.value}) - {len(gallery.pics)}张图片"
                if gallery.aliases:
                    msg += f" (别名: {', '.join(gallery.aliases)})"
                msg += "\n"
            await event.send(MessageChain([Plain(msg)]))
        except Exception as e:
            await event.send(MessageChain([Plain(f'列出画廊失败: {e}')]))

    @filter.command("/img test")
    async def img_test(self, event: AstrMessageEvent):
        """测试群合并转发消息"""
        try:
            from astrbot.api.message_components import Node, Plain, Image
            node = Node(
                uin=905617992,
                name="Soulter",
                content=[
                    Plain("这是一个群合并转发消息测试"),
                    Plain("你可以使用这种方式发送群合并转发消息")
                ]
            )
            yield event.chain_result([node])
        except Exception as e:
            await event.send(MessageChain([Plain(f'测试失败: {e}')]))
