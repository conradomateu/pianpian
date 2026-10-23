"""dmgbuild settings: the window you see when you open Pianpian-macOS.dmg.

    dmgbuild -s tools/dmg/settings.py -D app=dist/Pianpian.app -D icon=AppIcon.icns Pianpian dist/Pianpian-macOS.dmg

dmgbuild (pure Python) writes the layout itself instead of asking Finder through AppleScript, so it works the
same on a build server without a screen. Positions are the centres of the icons in the 660×400 window; the arrow
and the text are in background.tiff (tools/dmg/make_background.py).
"""
import os

app = defines.get("app", "dist/Pianpian.app")                       # noqa: F821  (defines comes from dmgbuild)
name = os.path.basename(app)
format = "ULFO"                                                     # lzfse: smaller and faster to open than zlib; macOS 10.11+
files = [app]
symlinks = {"Applications": "/Applications"}                        # the drop target
icon_locations = {name: (180, 190), "Applications": (480, 190)}
background = defines.get("background", "tools/dmg/background.tiff")   # noqa: F821  (run from the repository root)
badge_icon = defines.get("icon")                                    # noqa: F821  (the volume icon: the watermelon)
window_rect = ((200, 120), (660, 400))
default_view = "icon-view"
icon_size = 128
text_size = 13
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
