# -*- coding: utf-8 -*-
"""
指令图标（华为规范：「快捷指令优先显示符号 + 指令，保留原有字母」）
用 Pillow 图元绘制 14px 矢量符号，无外部图片依赖。
匹配不到时返回 False，渲染器自动退化为「纯文本」样式。
"""

from __future__ import annotations
from PIL import ImageDraw


def _b(d, box, c, w=1):
    d.rectangle(box, outline=c, width=w)


def _copy(d, x, y, s, c):
    d.rounded_rectangle((x + 1, y + 1, x + s - 4, y + s - 3), 2, outline=c, width=1)
    d.rounded_rectangle((x + 4, y + 4, x + s - 1, y + s - 1), 2, outline=c, width=1)


def _paste(d, x, y, s, c):
    d.rounded_rectangle((x + 2, y + 2, x + s - 2, y + s - 1), 1, outline=c, width=1)
    d.rectangle((x + 5, y, x + s - 5, y + 3), outline=c, width=1)
    d.line((x + 4, y + 5, x + s - 4, y + 5), fill=c)


def _cut(d, x, y, s, c):
    d.line((x + 2, y + 2, x + s - 3, y + s - 2), fill=c)
    d.line((x + s - 3, y + 2, x + 2, y + s - 2), fill=c)
    d.ellipse((x, y + s - 4, x + 4, y + s), outline=c)
    d.ellipse((x + s - 4, y + s - 4, x + s, y + s), outline=c)


def _save(d, x, y, s, c):
    d.rectangle((x + 1, y + 1, x + s - 1, y + s - 1), outline=c, width=1)
    d.rectangle((x + 4, y + 1, x + s - 4, y + 5), outline=c, width=1)
    d.rectangle((x + 4, y + 8, x + s - 4, y + s - 2), outline=c, width=1)


def _undo(d, x, y, s, c, flip=False):
    d.arc((x + 1, y + 1, x + s - 1, y + s - 1), 180, 350, fill=c, width=1)
    if flip:
        d.polygon([(x + s - 2, y + 2), (x + s - 2, y + 7), (x + s - 7, y + 4)], fill=c)
    else:
        d.polygon([(x + 1, y + 2), (x + 1, y + 7), (x + 6, y + 4)], fill=c)


def _redo(d, x, y, s, c):
    _undo(d, x, y, s, c, True)


def _select(d, x, y, s, c):
    for i in range(1, s - 1, 3):
        d.line((x + i, y + 1, x + i + 1, y + 1), fill=c)
        d.line((x + i, y + s - 1, x + i + 1, y + s - 1), fill=c)
        d.line((x + 1, y + i, x + 1, y + i + 1), fill=c)
        d.line((x + s - 1, y + i, x + s - 1, y + i + 1), fill=c)


def _find(d, x, y, s, c):
    d.ellipse((x + 1, y + 1, x + s - 5, y + s - 5), outline=c, width=1)
    d.line((x + s - 5, y + s - 5, x + s - 1, y + s - 1), fill=c, width=2)


def _zoom(d, x, y, s, c, plus=True):
    _find(d, x, y, s, c)
    cy = y + s // 2 - 2
    d.line((x + 3, cy, x + s - 7, cy), fill=c)
    if plus:
        d.line((x + (s - 4) // 2, cy - 2, x + (s - 4) // 2, cy + 2), fill=c)


def _print(d, x, y, s, c):
    d.rectangle((x + 3, y + 1, x + s - 3, y + 5), outline=c, width=1)
    d.rectangle((x + 1, y + 5, x + s - 1, y + s - 4), outline=c, width=1)
    d.rectangle((x + 4, y + s - 5, x + s - 4, y + s - 1), outline=c, width=1)


def _new(d, x, y, s, c):
    d.rounded_rectangle((x + 2, y + 1, x + s - 2, y + s - 1), 1, outline=c, width=1)
    d.line((x + s // 2, y + 4, x + s // 2, y + s - 4), fill=c)
    d.line((x + 5, y + s // 2, x + s - 5, y + s // 2), fill=c)


def _open(d, x, y, s, c):
    d.rectangle((x + 1, y + 4, x + s - 1, y + s - 1), outline=c, width=1)
    d.line((x + 1, y + 4, x + 4, y + 1, x + 8, y + 1), fill=c)


def _lock(d, x, y, s, c):
    d.arc((x + 3, y + 1, x + s - 3, y + 9), 180, 360, fill=c, width=1)
    d.rounded_rectangle((x + 1, y + 6, x + s - 1, y + s - 1), 1, outline=c, width=1)


def _trash(d, x, y, s, c):
    d.rectangle((x + 2, y + 3, x + s - 2, y + s - 1), outline=c, width=1)
    d.line((x + 1, y + 3, x + s - 1, y + 3), fill=c)
    d.line((x + 5, y + 1, x + s - 5, y + 1), fill=c)


def _refresh(d, x, y, s, c):
    d.arc((x + 1, y + 1, x + s - 1, y + s - 1), 30, 300, fill=c, width=1)
    d.polygon([(x + s - 4, y), (x + s, y), (x + s, y + 4)], fill=c)


def _window(d, x, y, s, c):
    d.rounded_rectangle((x + 1, y + 1, x + s - 1, y + s - 1), 1, outline=c, width=1)
    d.line((x + 1, y + 4, x + s - 1, y + 4), fill=c)


def _screenshot(d, x, y, s, c):
    d.rounded_rectangle((x + 1, y + 2, x + s - 1, y + s - 2), 1, outline=c, width=1)
    d.ellipse((x + s // 2 - 2, y + s // 2 - 2, x + s // 2 + 2, y + s // 2 + 2), outline=c)


def _terminal(d, x, y, s, c):
    d.rounded_rectangle((x + 1, y + 1, x + s - 1, y + s - 1), 1, outline=c, width=1)
    d.line((x + 3, y + 4, x + 6, y + 7, x + 3, y + 10), fill=c)
    d.line((x + 7, y + 10, x + s - 3, y + 10), fill=c)


def _link(d, x, y, s, c):
    d.arc((x + 1, y + 4, x + 8, y + s - 1), 90, 270, fill=c, width=1)
    d.arc((x + s - 8, y + 4, x + s - 1, y + s - 1), 270, 90, fill=c, width=1)
    d.line((x + 5, y + s // 2, x + s - 5, y + s // 2), fill=c)


def _align(d, x, y, s, c):
    d.line((x + 1, y + 3, x + s - 1, y + 3), fill=c)
    d.line((x + 1, y + 6, x + s - 4, y + 6), fill=c)
    d.line((x + 1, y + 9, x + s - 1, y + 9), fill=c)
    d.line((x + 1, y + 12, x + s - 5, y + 12), fill=c)


def _send(d, x, y, s, c):
    d.polygon([(x + 1, y + 2), (x + s - 1, y + 1), (x + s - 4, y + s - 1),
               (x + 5, y + 7)], outline=c)
    d.line((x + 1, y + 2, x + 5, y + 7), fill=c)


def _bookmark(d, x, y, s, c):
    d.polygon([(x + 2, y + 1), (x + s - 2, y + 1), (x + s - 2, y + s - 1),
               (x + s // 2, y + s - 5), (x + 2, y + s - 1)], outline=c)


def _help(d, x, y, s, c):
    d.ellipse((x + 1, y + 1, x + s - 1, y + s - 1), outline=c, width=1)
    d.arc((x + 4, y + 3, x + s - 4, y + 8), 0, 200, fill=c, width=1)
    d.line((x + s // 2, y + 7, x + s // 2, y + 9), fill=c)
    d.point((x + s // 2, y + 11), fill=c)


def _gear(d, x, y, s, c):
    import math
    d.ellipse((x + 3, y + 3, x + s - 3, y + s - 3), outline=c, width=1)
    d.ellipse((x + 6, y + 6, x + s - 6, y + s - 6), outline=c, width=1)
    cx, cy = x + s / 2, y + s / 2
    for i in range(0, 360, 45):
        a = math.radians(i)
        d.line((cx + 5 * math.cos(a), cy + 5 * math.sin(a),
                cx + 7 * math.cos(a), cy + 7 * math.sin(a)), fill=c)


def _arrow(d, x, y, s, c, direction="right"):
    cx, cy = x + s / 2, y + s / 2
    if direction == "right":
        pts = [(x + 1, cy - 1), (x + s - 4, cy - 1), (x + s - 4, cy - 4),
               (x + s - 1, cy), (x + s - 4, cy + 4), (x + s - 4, cy + 1), (x + 1, cy + 1)]
    elif direction == "left":
        pts = [(x + s - 1, cy - 1), (x + 4, cy - 1), (x + 4, cy - 4),
               (x + 1, cy), (x + 4, cy + 4), (x + 4, cy + 1), (x + s - 1, cy + 1)]
    elif direction == "up":
        pts = [(cx - 1, y + s - 1), (cx - 1, y + 4), (cx - 4, y + 4),
               (cx, y + 1), (cx + 4, y + 4), (cx + 1, y + 4), (cx + 1, y + s - 1)]
    else:
        pts = [(cx - 1, y + 1), (cx - 1, y + s - 4), (cx - 4, y + s - 4),
               (cx, y + s - 1), (cx + 4, y + s - 4), (cx + 1, y + s - 4), (cx + 1, y + 1)]
    d.polygon(pts, fill=c)


TABLE = [
    (("复制", "拷贝"), _copy),
    (("粘贴", "剪贴板"), _paste),
    (("剪切",), _cut),
    (("保存", "另存", "存为"), _save),
    (("撤销", "后退", "返回", "上一步"), lambda d, x, y, s, c: _undo(d, x, y, s, c)),
    (("重做", "恢复", "前进", "刷新", "重新加载", "还原"), _redo),
    (("全选", "选择", "选中", "选区"), _select),
    (("查找", "搜索", "定位", "跳转", "转到"), _find),
    (("放大", "增大", "上标"), lambda d, x, y, s, c: _zoom(d, x, y, s, c, True)),
    (("缩小", "减小", "下标", "折叠"), lambda d, x, y, s, c: _zoom(d, x, y, s, c, False)),
    (("打印", "放映", "投影"), _print),
    (("新建", "插入", "添加"), _new),
    (("打开", "文件夹", "资源管理器", "目录"), _open),
    (("锁", "隐私", "无痕", "安全"), _lock),
    (("删除", "清除", "关闭", "中断", "退出"), _trash),
    (("窗口", "桌面", "视图", "面板", "标签"), _window),
    (("截图", "截屏", "取色", "预览"), _screenshot),
    (("终端", "命令", "运行", "调试", "开发"), _terminal),
    (("链接", "超链接", "组合", "合并"), _link),
    (("对齐", "行距", "缩进", "列表", "格式", "字体", "大小"), _align),
    (("发送", "提交", "确认", "回车"), _send),
    (("收藏", "书签", "固定"), _bookmark),
    (("帮助", "属性", "说明"), _help),
    (("设置", "选项", "配置", "管理"), _gear),
    (("向右", "右移", "下一个", "下移", "向下", "下移行"), lambda d, x, y, s, c: _arrow(d, x, y, s, c, "right")),
    (("向左", "左移", "上一个", "上移", "向上"), lambda d, x, y, s, c: _arrow(d, x, y, s, c, "left")),
]


def draw_icon(d: ImageDraw.ImageDraw, label: str, x: int, y: int, s: int, color) -> bool:
    """在 (x,y) 画 s×s 图标；无匹配返回 False（调用方退化为纯文本）"""
    for keys, fn in TABLE:
        if any(k in label for k in keys):
            try:
                fn(d, int(x), int(y), int(s), color)
                return True
            except Exception:
                return False
    return False
