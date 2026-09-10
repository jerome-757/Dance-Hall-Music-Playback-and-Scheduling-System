# vu_meter.py
import tkinter as tk
import time

class VUMeter(tk.Canvas):
    """VU表控件类"""
    def __init__(self, parent, width=30, height=150, bg='#1a1a2e', **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.level = 0.0  # 当前电平值 0.0-1.0
        self.peak_level = 0.0  # 峰值电平
        self.peak_hold_time = 0  # 峰值保持时间
        self._draw_vu()
    
    def _draw_vu(self):
        """绘制VU表"""
        self.delete("all")
        
        # 计算绘制区域
        margin = 5
        bar_width = self.width - 2 * margin
        bar_height = self.height - 2 * margin
        
        # 绘制背景
        self.create_rectangle(margin, margin, margin + bar_width, margin + bar_height,
                            fill='#2a2a3e', outline='#3a3a4e', width=1)
        
        # 绘制刻度线
        num_ticks = 10
        for i in range(num_ticks + 1):
            y = margin + bar_height - (i * bar_height / num_ticks)
            tick_width = 5 if i % 2 == 0 else 3
            self.create_line(margin, y, margin + tick_width, y, fill='#666666', width=1)
            
            # 添加刻度标签
            if i % 2 == 0:
                value = int(i * 10)
                self.create_text(margin + bar_width + 5, y, text=str(value), 
                               fill='#888888', font=('Arial', 6), anchor='w')
        
        # 绘制电平条（从下往上）
        if self.level > 0:
            level_height = bar_height * self.level
            level_y1 = margin + bar_height - level_height
            level_y2 = margin + bar_height
            
            # 根据电平选择颜色
            if self.level < 0.6:
                color = '#00ff00'  # 绿色
            elif self.level < 0.8:
                color = '#ffff00'  # 黄色
            else:
                color = '#ff0000'  # 红色
            
            # 绘制渐变效果
            for y in range(int(level_y1), int(level_y2)):
                progress = (y - level_y1) / max(1, (level_y2 - level_y1))
                if progress < 0.6:
                    color = self._get_gradient_color(progress / 0.6, (0, 255, 0), (255, 255, 0))
                else:
                    color = self._get_gradient_color((progress - 0.6) / 0.4, (255, 255, 0), (255, 0, 0))
                self.create_line(margin + 2, y, margin + bar_width - 2, y, fill=color)
        
        # 绘制峰值指示器
        if self.peak_level > 0:
            peak_y = margin + bar_height - (bar_height * self.peak_level)
            self.create_line(margin, peak_y, margin + bar_width, peak_y, 
                           fill='#ffffff', width=2)
    
    def _get_gradient_color(self, progress, color1, color2):
        """获取渐变色"""
        # 确保progress在0-1范围内
        progress = max(0.0, min(1.0, progress))
        r1, g1, b1 = color1
        r2, g2, b2 = color2
        
        r = int(r1 + (r2 - r1) * progress)
        g = int(g1 + (g2 - g1) * progress)
        b = int(b1 + (b2 - b1) * progress)
        
        # 确保RGB值在0-255范围内
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        
        return f'#{r:02x}{g:02x}{b:02x}'
    
    def set_level(self, level):
        """设置电平值"""
        self.level = max(0.0, min(1.0, level))
        
        # 更新峰值
        if self.level > self.peak_level:
            self.peak_level = self.level
            self.peak_hold_time = time.time()
        
        # 峰值保持1秒后下降
        if time.time() - self.peak_hold_time > 1.0:
            self.peak_level = max(0.0, self.peak_level - 0.02)
        
        self._draw_vu()
