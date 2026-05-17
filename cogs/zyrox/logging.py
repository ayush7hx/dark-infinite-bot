import discord 
from discord .ext import commands 

class _logging (commands .Cog ):
    def __init__ (self ,bot ):
        self .bot =bot 

    """Logging commands"""

    def help_custom (self ):
		      emoji ='<:zcast:1504086037230653480>'
		      label ="Logging Commands"
		      description ="Shows you the commands of logging"
		      return emoji ,label ,description 

    @commands .group ()
    async def __Logging__ (self ,ctx :commands .Context ):
        """`log`, `log enable`, `log disable`, `log config`, `log ignore`, `log status`, `log toggle`"""
