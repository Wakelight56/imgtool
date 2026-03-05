import os
import shutil
import json
import hashlib
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple

from PIL import Image
import numpy as np

from astrbot.api import logger


class GalleryMode(Enum):
    Edit = 'edit'
    View = 'view'
    Off = 'off'


@dataclass
class GalleryPic:
    gall_name: str
    pid: int
    path: str
    hash1: str = None
    hash2: str = None
    thumb_path: Optional[str] = None

    @classmethod
    def load(cls, data: dict) -> 'GalleryPic':
        return cls(
            gall_name=data['gall_name'],
            pid=data['pid'],
            path=data['path'],
            hash1=data.get('hash1', None),
            hash2=data.get('hash2', None),
            thumb_path=data.get('thumb_path', None),
        )

    def calc_hash(self):
        image = Image.open(self.path)
        # 如果存在A通道：alphablend到纯白色背景上
        if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
            image = image.convert('RGBA').resize((64, 64), Image.Resampling.BILINEAR)
            bg = Image.new("RGBA", image.size, (255, 255, 255, 255))
            bg.alpha_composite(image)
            image = bg
        image = image.convert('RGB')
        image = image.resize((16, 16), Image.Resampling.BILINEAR).convert('L')
        # hash2: 用于MAE计算，直接转为hex字符串
        self.hash2 = image.tobytes().hex()
        # hash1: 用于快速比较，计算64位感知哈希
        image = image.resize((8, 8), Image.Resampling.BILINEAR)
        pixels = np.array(image).flatten()
        avg = pixels.mean()
        bits = 0
        for idx, p in enumerate(pixels):
            if p >= avg:
                bits |= 1 << (63 - idx)
        self.hash1 = f"{bits:016x}"

    def is_same(self, other: 'GalleryPic', hash1_threshold: int = 10, hash2_threshold: int = 1000) -> bool:
        # 通过hash1快速排除不同的图片
        if (int(self.hash1, 16) ^ int(other.hash1, 16)).bit_count() > hash1_threshold:
            return False
        # hash2精确判断
        img1 = np.frombuffer(bytes.fromhex(self.hash2), dtype=np.uint8)
        img2 = np.frombuffer(bytes.fromhex(other.hash2), dtype=np.uint8)
        diff = np.sum(np.abs(img1.astype(np.int16) - img2.astype(np.int16)))
        return diff <= hash2_threshold

    def ensure_thumb(self, thumb_size: Tuple[int, int] = (64, 64), bg_color: Tuple[int, int, int, int] = (230, 240, 255, 255)):
        try:
            if self.thumb_path is None:
                name = os.path.basename(self.path)
                self.thumb_path = os.path.join(os.path.dirname(self.path), f"{name}_thumb.jpg")
            if not os.path.exists(self.thumb_path):
                img = Image.open(self.path).convert('RGBA')
                img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                thumb = Image.new('RGBA', img.size, bg_color)
                thumb.alpha_composite(img)
                thumb.convert('RGB').save(self.thumb_path, format='JPEG', optimize=True, quality=85)
        except Exception as e:
            logger.warning(f'生成画廊图片 {self.pid} 缩略图失败: {e}')
            self.thumb_path = None


class GalleryPicRepeatedException(Exception):
    def __init__(self, pid: int):
        super().__init__(f'画廊中已存在相似图片(pid={pid})')
        self.pid = pid


@dataclass
class Gallery:
    name: str
    aliases: list[str]
    mode: GalleryMode
    pics_dir: str
    cover_pid: Optional[int] = None
    pics: list[GalleryPic] = field(default_factory=list)


class GalleryManager:
    _mgr: 'GalleryManager' = None

    def __init__(self, data_dir):
        # 确保data_dir是一个字符串
        if not isinstance(data_dir, str):
            data_dir = str(data_dir)
        self.data_dir = data_dir
        self.gallery_dir = os.path.join(self.data_dir, "gallery")
        if not os.path.exists(self.gallery_dir):
            os.makedirs(self.gallery_dir, exist_ok=True)
        self.db_path = os.path.join(self.gallery_dir, "gallery.json")
        self.pid_top = 0
        self.galleries: Dict[str, Gallery] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.pid_top = data.get('pid_top', 0)
                self.galleries = {}
                for name, g_data in data.get('galleries', {}).items():
                    self.galleries[name] = Gallery(
                        name=g_data['name'],
                        aliases=g_data.get('aliases', []),
                        cover_pid=g_data.get('cover_pid', None),
                        mode=GalleryMode(g_data.get('mode', 'edit')),
                        pics_dir=g_data['pics_dir'],
                        pics=[GalleryPic.load(p) for p in g_data.get('pics', [])],
                    )
                logger.info(f'成功加载{len(self.galleries)}个画廊, pid_top={self.pid_top}')
            except Exception as e:
                logger.error(f'加载画廊数据失败: {e}')
                self.pid_top = 0
                self.galleries = {}
        else:
            self.pid_top = 0
            self.galleries = {}

    def _save(self):
        try:
            data = {
                'pid_top': self.pid_top,
                'galleries': {}
            }
            for name, g in self.galleries.items():
                data['galleries'][name] = {
                    'name': g.name,
                    'aliases': g.aliases,
                    'cover_pid': g.cover_pid,
                    'mode': g.mode.value,
                    'pics_dir': g.pics_dir,
                    'pics': [
                        {
                            'gall_name': p.gall_name,
                            'pid': p.pid,
                            'path': p.path,
                            'hash1': p.hash1,
                            'hash2': p.hash2,
                            'thumb_path': p.thumb_path
                        }
                        for p in g.pics
                    ]
                }
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f'保存画廊数据失败: {e}')

    def _check_name(self, name: str) -> bool:
        if not name or len(name) > 32:
            return False
        if any(c in name for c in r'\/:*?"<>| '):
            return False
        if name.isdigit():
            return False
        return True

    def get_all_galls(self) -> Dict[str, Gallery]:
        """
        获取所有画廊
        """
        return self.galleries

    def find_gall(self, name_or_alias: str, raise_if_nofound: bool = False) -> Optional[Gallery]:
        """
        通过名称或别名查找画廊
        """
        for g in self.galleries.values():
            if g.name == name_or_alias or name_or_alias in g.aliases:
                return g
        if raise_if_nofound:
            if not name_or_alias:
                raise Exception('画廊名称不能为空')
            raise Exception(f'画廊"{name_or_alias}"不存在')
        return None

    def open_gall(self, name: str):
        """
        创建一个新画廊
        """
        assert self._check_name(name), f'画廊名称"{name}"无效'
        assert self.find_gall(name) is None, f'画廊"{name}"已存在'
        gall = Gallery(
            name=name,
            aliases=[],
            mode=GalleryMode.Edit,
            pics_dir=os.path.join(self.gallery_dir, name),
            pics=[],
        )
        self.galleries[name] = gall
        if not os.path.exists(gall.pics_dir):
            os.makedirs(gall.pics_dir, exist_ok=True)
        self._save()

    def close_gall(self, name_or_alias: str):
        """
        删除一个画廊
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊"{name_or_alias}"不存在'
        # 删除画廊目录
        try:
            if os.path.exists(g.pics_dir):
                shutil.rmtree(g.pics_dir)
        except Exception as e:
            logger.warning(f'删除画廊目录失败: {e}')
        self.galleries.pop(g.name)
        self._save()

    def add_gall_alias(self, name_or_alias: str, alias: str):
        """
        为画廊添加一个别名
        """
        assert self._check_name(alias), f'别名"{alias}"无效'
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊"{name_or_alias}"不存在'
        assert self.find_gall(alias) is None, f'别名"{alias}"已被占用'
        g.aliases.append(alias)
        self._save()

    def del_gall_alias(self, name_or_alias: str, alias: str):
        """
        删除画廊的一个别名
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊"{name_or_alias}"不存在'
        assert alias in g.aliases, f'别名"{alias}"不存在'
        g.aliases.remove(alias)
        self._save()

    def change_gall_mode(self, name_or_alias: str, mode: GalleryMode) -> Tuple[GalleryMode, GalleryMode]:
        """
        修改画廊的模式，返回(旧模式, 新模式)
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊"{name_or_alias}"不存在'
        old_mode = g.mode
        g.mode = mode
        self._save()
        return old_mode, g.mode

    def find_pic(self, pid: int, raise_if_nofound: bool = False) -> Optional[GalleryPic]:
        """
        通过图片ID查找图片
        """
        if pid < 0:
            pids = []
            for g in self.galleries.values():
                for p in g.pics:
                    pids.append(p.pid)
            pids.sort()
            if pid < -len(pids):
                if raise_if_nofound:
                    raise Exception(f'画廊仅有{len(pids)}张图片')
                return None
            pid = pids[pid]
        for g in self.galleries.values():
            for p in g.pics:
                if p.pid == pid:
                    return p
        if raise_if_nofound:
            raise Exception(f'画廊图片pid={pid}不存在')
        return None

    async def async_add_pic(self, name_or_alias: str, img_path: str, check_duplicated: bool = True) -> int:
        """
        向画廊添加一张图片，将会直接拷贝img_path的图片，返回图片ID
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊"{name_or_alias}"不存在'

        pic = GalleryPic(
            gall_name=g.name, 
            pid=self.pid_top+1,
            path=img_path, 
        )
        pic.calc_hash()

        if check_duplicated:
            if sim_pid := await self._async_check_duplicated(pic, g):
                raise GalleryPicRepeatedException(sim_pid)

        self.pid_top += 1
        _, ext = os.path.splitext(os.path.basename(img_path))
        time_str = os.path.basename(img_path).split('_')[0]
        if not time_str:
            from datetime import datetime
            time_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        dst_path = os.path.join(g.pics_dir, f"{time_str}_{self.pid_top}{ext}")
        if not os.path.exists(g.pics_dir):
            os.makedirs(g.pics_dir, exist_ok=True)
        shutil.copy2(img_path, dst_path)

        pic.path = dst_path
        g.pics.append(pic)
        pic.ensure_thumb()
        self._save()
        return self.pid_top

    async def _async_check_duplicated(self, pic: GalleryPic, gallery: Gallery) -> Optional[int]:
        """
        检查图片是否重复
        """
        for p in gallery.pics:
            if pic.is_same(p):
                return p.pid
        return None

    async def async_replace_pic(self, pid: int, img_path: str, check_duplicated: bool = True) -> int:
        """
        替换画廊中的一张图片，返回图片ID
        """
        p = self.find_pic(pid)
        assert p is not None, f'图片ID {pid} 不存在'
        g = self.find_gall(p.gall_name)
        assert g is not None, f'图片ID {pid} 所属画廊"{p.gall_name}"不存在'

        new_pic = GalleryPic(
            gall_name=g.name, 
            pid=p.pid, 
            path=img_path, 
        )
        new_pic.calc_hash()

        if check_duplicated:
            if sim_pid := await self._async_check_duplicated(new_pic, g):
                if sim_pid != pid:
                    raise GalleryPicRepeatedException(sim_pid)

        # 删除旧文件
        try:
            if os.path.exists(p.path):
                os.remove(p.path)
            if p.thumb_path and os.path.exists(p.thumb_path):
                os.remove(p.thumb_path)
        except Exception as e:
            logger.warning(f'删除画廊图片 {pid} 文件失败: {e}')

        # 复制新文件
        _, ext = os.path.splitext(os.path.basename(img_path))
        time_str = os.path.basename(img_path).split('_')[0]
        if not time_str:
            from datetime import datetime
            time_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        dst_path = os.path.join(g.pics_dir, f"{time_str}_{p.pid}{ext}")
        shutil.copy2(img_path, dst_path)

        # 更新信息
        p.path = dst_path
        p.hash1 = new_pic.hash1
        p.hash2 = new_pic.hash2
        p.thumb_path = None
        p.ensure_thumb()

        self._save()
        return p.pid

    def del_pic(self, pid: int) -> int:
        """
        从画廊删除一张图片，返回被删除的图片ID
        """
        p = self.find_pic(pid)
        assert p is not None, f'图片ID {pid} 不存在'
        g = self.find_gall(p.gall_name)
        g.pics.remove(p)
        try:
            if os.path.exists(p.path):
                os.remove(p.path)
            if p.thumb_path and os.path.exists(p.thumb_path):
                os.remove(p.thumb_path)
        except Exception as e:
            logger.warning(f'删除画廊图片 {pid} 文件失败: {e}')
        self._save()
        return p.pid

    def set_cover_pic(self, name_or_alias: str, pid: int):
        """
        设置画廊封面图片
        """
        g = self.find_gall(name_or_alias)
        assert g is not None, f'画廊"{name_or_alias}"不存在'
        p = self.find_pic(pid)
        assert p is not None and p.gall_name == g.name, f'图片pid={pid}不属于画廊"{g.name}"'
        g.cover_pid = pid
        self._save()

    @classmethod
    def get(cls, data_dir) -> 'GalleryManager':
        if cls._mgr is None:
            cls._mgr = GalleryManager(data_dir)
        return cls._mgr
