import asyncio

async def sleep_probe():
    i = 0
    while i < 5:
        await asyncio.sleep(2.0)
        i += 1
        print(f"[SLEEP-PROBE] tick={i}")

async def main():
    asyncio.create_task(sleep_probe())
    await asyncio.sleep(15.0)
    print("main done")

if __name__ == "__main__":
    asyncio.run(main())
