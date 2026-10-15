"""Раскладка установочного образа для dmgbuild.

Через Finder её задать нельзя: AppleScript требует доступа к автоматизации
и на чужой машине молча не срабатывает. dmgbuild пишет .DS_Store напрямую.
"""
import os

app = os.path.join(os.getcwd(), "build", "Severance.app")

files = [app]
symlinks = {"Applications": "/Applications"}
volume_name = "Severance"
format = "UDZO"
compression_level = 9

icon_size = 128
window_rect = ((260, 220), (560, 340))      # положение и размер окна
icon_locations = {
    "Severance.app": (150, 150),
    "Applications": (410, 150),
}
background = "#1e1e20"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
default_view = "icon-view"
arrange_by = None
text_size = 13
label_pos = "bottom"
