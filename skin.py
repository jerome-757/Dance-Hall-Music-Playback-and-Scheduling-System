# ==================== skin.py（终极强制版 - 修复） ====================
import tkinter as tk
from tkinter import ttk

def apply_skin_to_player(player):
    """为 DanceMusicPlayer 实例应用霓虹电音皮肤 - 强制递归版"""
    
    COLORS = {
        # 深灰背景
        'bg_primary': '#0a0e17',
        'bg_secondary': '#111927',
        'bg_tertiary': '#1a2744',
        'bg_card': '#0f1a2e',
        'bg_input': '#1a2a4a',
        'bg_table_odd': '#161b22',
        'bg_table_even': '#0d1117',

        # 霓虹蓝为主色
        'neon_blue': '#00d4ff',
        'neon_blue_dim': '#007a99',
        'neon_blue_glow': '#00d4ff',
        
        # 点缀色（仅用于重要状态）
        'neon_pink': '#ff2d95',
        'neon_purple': '#b026ff',
        'neon_green': '#39ff14',
        'neon_orange': '#ff6a00',
        'neon_yellow': '#ffe600',

        # 文字层级
        'text_primary': '#e8f0ff',
        'text_secondary': '#8899cc',
        'text_dim': '#445577',
        'text_bright': '#ffffff',
    }
    
    # ===== 1. 配置 ttk 样式 =====
    try:
        style = ttk.Style()
        style.theme_use('clam')
        
        # Treeview - 深色表格
        style.configure('Treeview',
                        background=COLORS['bg_secondary'],
                        foreground=COLORS['text_primary'],
                        fieldbackground=COLORS['bg_secondary'],
                        rowheight=30,
                        borderwidth=0,
                        font=('Consolas', 10))
        style.map('Treeview',
                  background=[('selected', COLORS['neon_purple'])],
                  foreground=[('selected', '#0a0e17')])
        
        # Treeview.Heading - 霓虹蓝表头
        style.configure('Treeview.Heading',
                        background=COLORS['bg_tertiary'],
                        foreground=COLORS['neon_blue'],
                        relief='flat',
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Treeview.Heading',
                  background=[('active', COLORS['bg_tertiary'])],
                  foreground=[('active', COLORS['text_primary'])])
        
        # 滚动条 - 低调蓝色
        style.configure('Vertical.TScrollbar',
                        background=COLORS['bg_tertiary'],
                        troughcolor=COLORS['bg_primary'],
                        bordercolor=COLORS['bg_primary'],
                        arrowcolor=COLORS['neon_blue_dim'],
                        width=8)
        style.map('Vertical.TScrollbar',
                  background=[('active', COLORS['neon_blue_dim'])],
                  arrowcolor=[('active', COLORS['neon_blue'])])
        
        style.configure('Horizontal.TScrollbar',
                        background=COLORS['bg_tertiary'],
                        troughcolor=COLORS['bg_primary'],
                        bordercolor=COLORS['bg_primary'],
                        arrowcolor=COLORS['neon_blue_dim'],
                        height=8)
        style.map('Horizontal.TScrollbar',
                  background=[('active', COLORS['neon_blue_dim'])],
                  arrowcolor=[('active', COLORS['neon_blue'])])
        
        # 进度条 - 霓虹蓝渐变
        style.configure('TProgressbar',
                        background=COLORS['neon_blue'],
                        troughcolor=COLORS['bg_tertiary'],
                        bordercolor=COLORS['bg_tertiary'],
                        lightcolor=COLORS['neon_blue'],
                        darkcolor=COLORS['neon_blue_dim'])
        
        # Scale - 霓虹蓝滑块
        style.configure('TScale',
                        background=COLORS['bg_secondary'],
                        troughcolor=COLORS['bg_tertiary'],
                        slidercolor=COLORS['neon_blue'],
                        sliderrelief='flat',
                        borderwidth=0)
        style.map('TScale',
                  slidercolor=[('active', COLORS['neon_pink'])])
    except:
        pass
    
    # ===== 2. 强制递归配置所有组件 =====
    def force_configure(widget, depth=0):
        """强制递归设置所有子组件的颜色"""
        if depth > 20:
            return
        
        try:
            widget_class = widget.winfo_class()
        except:
            return
        
        try:
            if widget_class == 'Frame':
                widget.configure(bg=COLORS['bg_secondary'])
            elif widget_class == 'Label':
                    widget.configure(bg=COLORS['bg_secondary'], fg=COLORS['text_secondary'])
            elif widget_class == 'Text':
                widget.configure(bg=COLORS['bg_input'], 
                               fg=COLORS['text_secondary'],
                               relief='flat',
                               highlightthickness=0,
                               insertbackground=COLORS['neon_blue'])
            elif widget_class == 'Scale':
                widget.configure(bg=COLORS['bg_secondary'],
                               troughcolor=COLORS['bg_tertiary'],
                               highlightthickness=0)
            elif widget_class == 'Button':
                try:
                    current_bg = widget.cget('bg')
                    if current_bg not in ['#2ecc71', '#f1c40f', '#e74c3c']:
                        widget.configure(bg=COLORS['bg_tertiary'], 
                                       fg=COLORS['text_secondary'],
                                       activebackground=COLORS['bg_tertiary'],
                                       activeforeground=COLORS['text_secondary'])
                except:
                    pass
            elif widget_class == 'Listbox':
                widget.configure(bg=COLORS['bg_secondary'],
                               fg=COLORS['text_secondary'],
                               selectbackground=COLORS['neon_blue'])
            elif widget_class == 'Canvas':
                widget.configure(bg=COLORS['bg_secondary'])
        except:
            pass
        
        try:
            for child in widget.winfo_children():
                force_configure(child, depth + 1)
        except:
            pass
    
    # ===== 3. 从根窗口开始强制配置 =====
    try:
        player.root.configure(bg=COLORS['bg_primary'])
        force_configure(player.root)
    except Exception as e:
        print(f"⚠️ 强制配置失败: {e}")
    
    # ===== 4. 状态栏 =====
    if hasattr(player, 'status_frame') and player.status_frame:
        try:
            player.status_frame.configure(bg=COLORS['bg_tertiary'])
            for child in player.status_frame.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=COLORS['bg_tertiary'])
        except:
            pass
    
    # ===== 5. 辅助信息栏 =====
    if hasattr(player, 'helper_frame') and player.helper_frame:
        try:
            player.helper_frame.configure(bg=COLORS['bg_tertiary'])
        except:
            pass
    if hasattr(player, 'helper_label') and player.helper_label:
        try:
            player.helper_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['text_secondary'])
        except:
            pass
    
    # ===== 6. 控制按钮 =====
    if hasattr(player, 'play_btn') and player.play_btn:
        try:
            player.play_btn.configure(bg=COLORS['neon_green'], fg='#0a0e17',
                                     activebackground=COLORS['neon_green'],
                                     activeforeground='#0a0e17', relief='flat')
        except:
            pass
    
    if hasattr(player, 'pause_btn') and player.pause_btn:
        try:
            player.pause_btn.configure(bg=COLORS['neon_yellow'], fg='#0a0e17',
                                      activebackground=COLORS['neon_yellow'],
                                      activeforeground='#0a0e17', relief='flat')
        except:
            pass
    
    if hasattr(player, 'stop_btn') and player.stop_btn:
        try:
            player.stop_btn.configure(bg=COLORS['neon_pink'], fg='#0a0e17',
                                     activebackground=COLORS['neon_pink'],
                                     activeforeground='#0a0e17', relief='flat')
        except:
            pass
    
    # ===== 7. 时间标签 =====
    if hasattr(player, 'current_time_label') and player.current_time_label:
        try:
            player.current_time_label.configure(bg=COLORS['bg_secondary'], 
                                               fg=COLORS['text_dim'],
                                               font=('Consolas', 14))
        except:
            pass
    
    if hasattr(player, 'total_time_label') and player.total_time_label:
        try:
            player.total_time_label.configure(bg=COLORS['bg_secondary'],
                                             fg=COLORS['neon_blue'],
                                             font=('Consolas', 12, 'bold'))
        except:
            pass
    
    # ===== 8. 状态标签 =====
    if hasattr(player, 'status_play_mode_label') and player.status_play_mode_label:
        try:
            player.status_play_mode_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['neon_orange'])
        except:
            pass
    if hasattr(player, 'status_position_label') and player.status_position_label:
        try:
            player.status_position_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['neon_yellow'])
        except:
            pass
    
    if hasattr(player, 'status_time_display_label') and player.status_time_display_label:
        try:
            player.status_time_display_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['neon_blue'])
        except:
            pass
    
    if hasattr(player, 'percent_label') and player.percent_label:
        try:
            player.percent_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['neon_green'])
        except:
            pass
    
    if hasattr(player, 'status_label') and player.status_label:
        try:
            player.status_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['text_primary'])
        except:
            pass
    
    if hasattr(player, 'status_time_label') and player.status_time_label:
        try:
            player.status_time_label.configure(bg=COLORS['bg_tertiary'], fg=COLORS['text_secondary'])
        except:
            pass
    
    # ===== 9. VU表 =====
    if hasattr(player, 'left_vu_meter') and player.left_vu_meter:
        try:
            player.left_vu_meter.configure(bg='#0a0e17')
        except:
            pass
    if hasattr(player, 'right_vu_meter') and player.right_vu_meter:
        try:
            player.right_vu_meter.configure(bg='#0a0e17')
        except:
            pass
    
    # ===== 10. 播放列表按钮 =====
    if hasattr(player, 'playlist_buttons') and player.playlist_buttons:
        neon_colors = [
            COLORS['neon_blue'],
            COLORS['neon_pink'],
            COLORS['neon_purple'],
            COLORS['neon_green'],
            COLORS['neon_orange'],
            COLORS['neon_yellow']
        ]
        for i, (pid, btn) in enumerate(player.playlist_buttons.items()):
            try:
                color = neon_colors[i % len(neon_colors)]
                btn.configure(bg=color, fg='#0a0e17', relief='flat',
                             activebackground=color, activeforeground='#0a0e17')
            except:
                pass
    
    # ===== 11. 框架 =====
    if hasattr(player, 'left_frame') and player.left_frame:
        try:
            player.left_frame.configure(bg=COLORS['bg_secondary'])
        except:
            pass
    
    if hasattr(player, 'right_frame') and player.right_frame:
        try:
            player.right_frame.configure(bg=COLORS['bg_secondary'])
        except:
            pass
    
    if hasattr(player, 'top_btn_frame') and player.top_btn_frame:
        try:
            player.top_btn_frame.configure(bg=COLORS['bg_tertiary'])
        except:
            pass
    
    if hasattr(player, 'top_frame') and player.top_frame:
        try:
            player.top_frame.configure(bg=COLORS['bg_primary'])
        except:
            pass
    
    if hasattr(player, 'bottom_frame') and player.bottom_frame:
        try:
            player.bottom_frame.configure(bg=COLORS['bg_secondary'])
        except:
            pass
    
    # ===== 12. 菜单栏 =====
    try:
        player.root.option_add('*Menu.background', COLORS['bg_secondary'])
        player.root.option_add('*Menu.foreground', COLORS['neon_blue'])
        player.root.option_add('*Menu.selectColor', COLORS['neon_purple'])
        player.root.option_add('*Menu.activebackground', COLORS['bg_tertiary'])
        player.root.option_add('*Menu.activeforeground', COLORS['neon_pink'])
    except:
        pass

    # ===== 13. 查找并配置音频控制区的 Label =====
    try:
        for child in player.bottom_frame.winfo_children():
            if isinstance(child, tk.Frame):
                for sub in child.winfo_children():
                    if isinstance(sub, tk.Label):
                        try:
                            text = sub.cget('text')
                            # 均衡器频率标签和速度、音调等标签用 neon_blue_dim
                            if text in ['节拍', '速度', '音调', '文件名', '文件大小', 
                                    '节拍速度', '比特率', '采样率', '声道数', '位深度']:
                                sub.configure(fg=COLORS['neon_blue_dim'], bg=COLORS['bg_secondary'])
                            # 均衡器 HZ 文字（包含 Hz 后缀的标签）
                            elif 'Hz' in text or 'HZ' in text:
                                sub.configure(fg=COLORS['neon_blue_dim'], bg=COLORS['bg_secondary'])
                            else:
                                sub.configure(fg=COLORS['text_blue_dim'], bg=COLORS['bg_secondary'])
                        except:
                            pass
    except:
        pass

    # ===== 15. 刷新 =====
    try:
        player.root.update_idletasks()
    except:
        pass
    
    print("🎨 霓虹电音皮肤已强制应用！🚀")
    return COLORS