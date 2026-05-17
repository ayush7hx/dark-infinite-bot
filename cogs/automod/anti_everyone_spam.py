import discord
from discord.ext import commands

SPAM_KEYWORDS = [
    'casino', 'gambl', 'win free', 'crypto', 'bitcoin', 'earn money',
    'free nitro', 'click here', 'giveaway discord', 'withdraw',
    'profit', 'investment', 'airdrop', 'stake.com', 'bonus', 'forex',
    'csgo', 'click the link', 'join now', 'limited time', '18+',
    'sexy', 'nude', 'onlyfans', 'dating', 'cheap followers',
]

class AntiEveryoneSpam(commands.Cog, name="AntiEveryoneSpam"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        content = message.content.lower()

        # Must contain @everyone or @here text
        has_ping = '@everyone' in content or '@here' in content
        if not has_ping:
            return

        # Spam indicators
        has_keyword   = any(kw in content for kw in SPAM_KEYWORDS)
        many_attach   = len(message.attachments) >= 2
        has_ext_link  = ('http://' in content or 'https://' in content) and 'discord.com' not in content
        has_inv_link  = 'discord.gg/' in content

        is_spam = has_keyword or many_attach or (has_ext_link and has_inv_link)
        if not is_spam:
            return

        # Delete regardless of sender role/permissions (even owner)
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        # Silent log to bot console
        print(f"[AntiEveryoneSpam] Deleted spam from {message.author} in {message.guild.name} / #{message.channel.name}")


async def setup(bot):
    await bot.add_cog(AntiEveryoneSpam(bot))
