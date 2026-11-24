# Feature Popup

QGIS plugin (3.28+ and 4.x): click a feature to get a modern, card-based attribute popup.

## Install

**From a ZIP:** download [feature_popup.zip](https://github.com/knl88/qgis-feature-popup/releases/latest/download/feature_popup.zip) (latest release), then in QGIS open *Plugins → Manage and Install Plugins → Install from ZIP*.

**For development:** link the folder into your profile's plugins directory:

```bash
ln -s "$PWD/feature_popup" ~/.local/share/QGIS/QGIS4/profiles/default/python/plugins/
```

On QGIS 3, use `QGIS3` in that path instead of `QGIS4`.

Restart QGIS, then enable **Feature Popup** under *Plugins → Manage and Install Plugins → Installed*.

## Use

Turn on the tool with the toolbar button or *Web → Feature Popup*.

| Action | Result |
|---|---|
| Click on the map | Shows the features at that point |
| Drag on the map | Pans the map |
| Esc / right-click | Closes the popup |
| Drag the header / corner | Moves / resizes the popup |
| Double-click the header | Docks the popup again |
| Ctrl+F | Filters attributes |

Settings: *Web → Feature Popup → Settings…*

## Release

Bump `version=` in `feature_popup/metadata.txt`, commit, then push a matching tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

GitHub Actions builds `feature_popup.zip` and attaches it to a new release.
