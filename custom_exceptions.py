class DirMissing(Exception):
    """docstring for CheatsMissing."""
    def __init__(self,*args,**kwargs):
        Exception.__init__(self,*args,**kwargs)

class OutDirNotEmpty(Exception):
    """docstring"""
    def __init__(self,*args,**kwargs):
        Exception.__init__(self,*args,**kwargs)
