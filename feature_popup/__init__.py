def classFactory(iface):
    from .plugin import FeaturePopupPlugin

    return FeaturePopupPlugin(iface)
