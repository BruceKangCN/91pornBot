import asyncio

import uvloop

from pyp.play import getMaDou, getHs, getVideoInfo91, page91Index, get91Home

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
import datetime
import os
import shutil

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import redis
from telethon import TelegramClient, events
from urllib import parse

import util


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASS")
API_ID = int(os.getenv("API_ID", ""))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", ""))
cron_hour_91 = int(os.getenv("CRON_HOUR_91", "6"))
cron_minute_91 = int(os.getenv("CRON_MINUTE_91", "50"))


bot = TelegramClient(None, API_ID, API_HASH).start(bot_token=BOT_TOKEN)
redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, db=1, decode_responses=True)


async def saveToRedis(key, message_id, user_id):
    redis_conn.set(key, f"{message_id},{user_id}")


async def getFromRedis(key):
    value = redis_conn.get(key)
    if value is None:
        return 0, 0
    msgList = value.split(",")
    return int(msgList[0]), int(msgList[1])


@bot.on(events.NewMessage(pattern="/start"))
async def send_simple_help(event):
    await event.client.send_message(event.chat_id, "向我发送91视频链接，获取视频，有问题请留言 `/help` 查看详情")


@bot.on(events.NewMessage(pattern="/get91home"))
async def send_91home(event):
    await event.client.send_message(event.chat_id, f"免翻地址: {await get91Home()}")


@bot.on(events.NewMessage(pattern="/revideo91"))
async def send_video(event):
    await event.client.send_message(event.chat_id, "开始执行爬取.....")
    await page91DownIndex()
    await event.client.send_message(event.chat_id, "执行爬取结束.....")

@bot.on(events.NewMessage(pattern="/help"))
async def send_detailed_help(event):
    await event.client.send_message(event.chat_id, """向我发送91视频网站内 https://91porn.com/ 的视频链接，获取视频。
如发送的链接后，没收到视频原因是部分高清视频刚发布后还在转码，大概在视频发布时间一小时后再尝试发送链接下载。
""")


@bot.on(events.NewMessage)
async def echo_all(event):
    text = event.text
    sender = await event.get_sender()

    if event.is_private:
        if "viewkey" in text:  # 处理91的视频
            params = parse.parse_qs(parse.urlparse(text).query)
            viewkey = params["viewkey"][0]
            viewkey_url = f"https://91porn.com/view_video.php?viewkey={viewkey}"

            # redis查询历史数据
            mid, uid = await getFromRedis(viewkey)
            try:
                await event.client.forward_messages(event.chat_id, mid, uid)
                return
            except:
                print("消息已被删除或不存在，无法转发")
            await handle91(event, viewkey, viewkey_url)
        elif "hsex.men/video-" in text:  # 补充,不向redis存了
            sender = await event.get_sender()
            await handleHs(event, sender, text)
        elif "/vod/play/id" in text:
            # 解析视频id
            path: str = parse.urlparse(text).path
            viewkey = f"md{path.split('/')[5]}"
            viewkey_url = text

            # redis查询历史数据
            mid, uid = await getFromRedis(viewkey)
            try:
                await event.client.forward_messages(event.chat_id, mid, uid)
                return
            except:
                print("消息已被删除或不存在，无法转发")
            await handleMd(event, viewkey, viewkey_url)



async def handleMd(event, viewkey, viewkey_url):
    # 获取视频信息
    try:
        m3u8Url, title = await getMaDou(viewkey_url)
        msg1 = await event.client.send_message(event.chat_id,
                                               f"真实视频地址:{m3u8Url}，正在下载中...，请不要一次性发送大量链接，被发现后会被封禁！！！")

        await util.download91(m3u8Url, viewkey)
        # 截图
        await util.imgCoverFromFile(f"{viewkey}/{viewkey}.mp4", f"{viewkey}/{viewkey}.jpg")
        msg = await event.reply("视频下载完成，正在上传。。。如果长时间没收到视频，请重新发送链接")

        # 发送视频
        message = await event.client.send_file(event.chat_id,
                                                f"{viewkey}/{viewkey}.mp4",
                                                supports_streaming=True,
                                                thumb=f"{viewkey}/{viewkey}.jpg",
                                                caption=f"标题: {title}\n",
                                                reply_to=event.id,
                                            )
        await msg.delete()
        await msg1.delete()
        await saveToRedis(viewkey, message.id, message.peer_id.user_id)

        print(f"{datetime.datetime.now()}: {title} 发送成功")
    finally:
        shutil.rmtree(viewkey, ignore_errors=True)


async def handleHs(event, sender, text):
    p = parse.urlparse(text)
    viewkey = p.path.replace("/", "")
    print(f"消息来自: {sender.username}: {text}")
    try:
        videoInfo = await getHs(text)
        await util.download91(videoInfo.realM3u8, viewkey, 5)
        # 截图
        await util.imgCoverFromFile(f"{viewkey}/{viewkey}.mp4", f"{viewkey}/{viewkey}.jpg")
        segstr = await util.seg(videoInfo.title)
        msg = await event.reply("视频下载完成，正在上传。。。如果长时间没收到视频，请重新发送链接")
        # 发送视频
        await event.client.send_file(event.chat_id,
                                        f"{viewkey}/{viewkey}.mp4",
                                        supports_streaming=True,
                                        thumb=f"{viewkey}/{viewkey}.jpg",
                                        caption=f"标题: {videoInfo.title}\n收藏: 000\n作者: #{videoInfo.author}\n关键词： {segstr}\n",
                                        reply_to=event.id,
                                    )
        await msg.delete()

        print(f"{datetime.datetime.now()}: {videoInfo.title} 发送成功")
    finally:
        shutil.rmtree(viewkey, ignore_errors=True)





async def handle91(event, viewkey, viewkey_url):
    try:
        videoinfo, err_msg = await getVideoInfo91(viewkey_url)

        if err_msg is not None:
            await event.reply(
                err_msg)
            return
        msg1 = await event.client.send_message(event.chat_id,
                                               f"真实视频地址: {videoinfo.realM3u8}，正在下载中...，请不要一次性发送大量链接，被发现后会被封禁！！！")
        title = videoinfo.title
        if not os.path.exists(viewkey):
            os.makedirs(viewkey)

        if ".mp4" in videoinfo.realM3u8:
            await  util.run(videoinfo.realM3u8, viewkey)
        else:

            try:
                await util.download91(videoinfo.realM3u8, viewkey)
            except ValueError:
                await event.reply("该视频高清版转码未完成,请等待转码完成后再发送链接,转码完成一般在视频发布1小时后")
                return

        # 截图
        await util.imgCoverFromFile(f"{viewkey}/{viewkey}.mp4", f"{viewkey}/{viewkey}.jpg")
        segstr = await util.seg(title)


        await cut_video91(viewkey)
        msg = await event.reply("视频下载完成，正在上传。。。如果长时间没收到视频，请重新发送链接")
        # 发送视频
        message = await event.client.send_file(event.chat_id,
                                                f"{viewkey}/seg_{viewkey}.mp4",
                                                supports_streaming=True,
                                                thumb=f"{viewkey}/{viewkey}.jpg",
                                                caption=f"标题: {title}\n收藏: {videoinfo.scCount}\n作者: #{videoinfo.author}\n关键词： {segstr}\n",
                                                reply_to=event.id,
                                            )
        await msg.delete()
        await msg1.delete()

        await saveToRedis(viewkey, message.id, message.peer_id.user_id)
        print(f"{datetime.datetime.now()}: {title} 发送成功")
    finally:
        shutil.rmtree(viewkey, ignore_errors=True)


async def cut_video91(viewkey):
    # 获取视频时长
    duration = util.getVideoDuration(f"{viewkey}/{viewkey}.mp4")
    await util.segVideo(f"{viewkey}/{viewkey}.mp4", f"{viewkey}/seg_{viewkey}.mp4",
                        start="0" if duration < 2 * 60 else "10")


async def page91DownIndex():
    """首页视频下载发送"""

    urls, titles, authors, scCounts = await page91Index()
    for i in range(len(urls)):
        url = urls[i]
        params = parse.parse_qs(parse.urlparse(url).query)
        viewkey = params["viewkey"][0]

        try:
            videoinfo, err_msg = await getVideoInfo91(url)
            if err_msg is not None:
                continue
            # 下载视频
            await util.download91(videoinfo.realM3u8, viewkey)
        except:
            print("转码失败")
            shutil.rmtree(viewkey, ignore_errors=True)
            continue

        # 截图
        await util.imgCoverFromFile(viewkey + '/' + viewkey + '.mp4', viewkey + '/' + viewkey + '.jpg')
        segstr = await util.seg(titles[i])
        # 发送视频

        await cut_video91(viewkey)

        message = await bot.send_file(GROUP_ID,
                                        f"{viewkey}/seg_{viewkey}.mp4",
                                        supports_streaming=True,
                                        thumb=f"{viewkey}/{viewkey}.jpg",
                                        caption=f"标题: {titles[i]}\n收藏: {scCounts[i]}\n作者: #{authors[i].strip()}\n关键词: {segstr}\n",
                                      )
        shutil.rmtree(viewkey, ignore_errors=True)
        await saveToRedis(viewkey, message.id, GROUP_ID)


async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(page91DownIndex, "cron", hour=cron_hour_91, minute=cron_minute_91)
    scheduler.start()
    print("bot 启动了！！！")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        pass
