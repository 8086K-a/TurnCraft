from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from agent.config.config_loader import settings


class Database:
    def __init__(self):
        self._engine = None
        self._sessionmaker = None

    def init(self):
        """初始化（只执行一次）"""
        if self._engine is None:
            self._engine = create_async_engine(
                settings.db_url,
                echo=False,
                pool_size=10,
                max_overflow=20,
            )

            self._sessionmaker = async_sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )

    async def close(self):
        """关闭连接池"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取 session（推荐用法）"""
        if self._sessionmaker is None:
            self.init()

        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

db = Database()
# async def main():
#
#     async with db.session() as session:
#         result = await session.execute(text('SELECT 1;'))
#         print(result.scalar())
#     await db.close()

# if __name__ == '__main__':
#     asyncio.run(main())
