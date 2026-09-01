# Third-Party Notices / 第三方声明

本文件是工程清单，不是法律意见，也不授予任何第三方权利。根目录 `LICENSE` 的 MIT License 只覆盖项目自有代码和明确标记为项目自建的内容；第三方软件、文章、模型、数据和服务继续受各自上游条款约束。

## 清单规则

- 只列 `pyproject.toml` 与 `frontend/package.json` **直接声明**的依赖，不把 lockfile 中的传递依赖冒充直接依赖。
- 版本保持与 manifest 一致；extra（如 `[binary]`、`[standard]`、`[toml]`）仍指向同一上游项目。
- 每项同时给出精确版本发布页和上游仓库的 LICENSE endpoint。LICENSE endpoint 展示默认分支的当前文件；最终审计必须再核对所用版本 tag/source distribution 内的许可证、notice 和例外，不能由本清单推断结论。
- 这里不摘录、不命名、不保证任何第三方许可证类型。链接失效、仓库迁移或版本差异都需要发行者重新核验。
- 容器基础镜像、系统包、外部数据库/对象存储/模型服务和传递依赖需由最终发行物另行生成 SBOM 并审计，本清单不声称覆盖它们。

## Python 直接依赖

### 构建

- `setuptools==84.0.0` — [发布页](https://pypi.org/project/setuptools/84.0.0/) · [上游 LICENSE](https://api.github.com/repos/pypa/setuptools/license)
- `wheel==0.48.0` — [发布页](https://pypi.org/project/wheel/0.48.0/) · [上游 LICENSE](https://api.github.com/repos/pypa/wheel/license)

### Core runtime

- `alembic==1.19.1` — [发布页](https://pypi.org/project/alembic/1.19.1/) · [上游 LICENSE](https://api.github.com/repos/sqlalchemy/alembic/license)
- `anyio==4.14.2` — [发布页](https://pypi.org/project/anyio/4.14.2/) · [上游 LICENSE](https://api.github.com/repos/agronholm/anyio/license)
- `argon2-cffi==25.1.0` — [发布页](https://pypi.org/project/argon2-cffi/25.1.0/) · [上游 LICENSE](https://api.github.com/repos/hynek/argon2-cffi/license)
- `fastapi==0.141.1` — [发布页](https://pypi.org/project/fastapi/0.141.1/) · [上游 LICENSE](https://api.github.com/repos/fastapi/fastapi/license)
- `minio==7.2.20` — [发布页](https://pypi.org/project/minio/7.2.20/) · [上游 LICENSE](https://api.github.com/repos/minio/minio-py/license)
- `psycopg[binary]==3.3.4` — [发布页](https://pypi.org/project/psycopg/3.3.4/) · [上游 LICENSE](https://api.github.com/repos/psycopg/psycopg/license)
- `pydantic==2.10.4` — [发布页](https://pypi.org/project/pydantic/2.10.4/) · [上游 LICENSE](https://api.github.com/repos/pydantic/pydantic/license)
- `pydantic-settings==2.15.0` — [发布页](https://pypi.org/project/pydantic-settings/2.15.0/) · [上游 LICENSE](https://api.github.com/repos/pydantic/pydantic-settings/license)
- `python-dotenv==1.2.3` — [发布页](https://pypi.org/project/python-dotenv/1.2.3/) · [上游 LICENSE](https://api.github.com/repos/theskumar/python-dotenv/license)
- `python-multipart==0.0.32` — [发布页](https://pypi.org/project/python-multipart/0.0.32/) · [上游 LICENSE](https://api.github.com/repos/Kludex/python-multipart/license)
- `SQLAlchemy==2.0.52` — [发布页](https://pypi.org/project/SQLAlchemy/2.0.52/) · [上游 LICENSE](https://api.github.com/repos/sqlalchemy/sqlalchemy/license)
- `starlette==1.6.0` — [发布页](https://pypi.org/project/starlette/1.6.0/) · [上游 LICENSE](https://api.github.com/repos/Kludex/starlette/license)
- `uvicorn[standard]==0.34.0` — [发布页](https://pypi.org/project/uvicorn/0.34.0/) · [上游 LICENSE](https://api.github.com/repos/encode/uvicorn/license)

### Optional runtime

- `datasets==5.0.1` — [发布页](https://pypi.org/project/datasets/5.0.1/) · [上游 LICENSE](https://api.github.com/repos/huggingface/datasets/license)
- `FlagEmbedding==1.4.2` — [发布页](https://pypi.org/project/FlagEmbedding/1.4.2/) · [上游 LICENSE](https://api.github.com/repos/FlagOpen/FlagEmbedding/license)
- `langchain-core==1.6.1` — [发布页](https://pypi.org/project/langchain-core/1.6.1/) · [上游 LICENSE](https://api.github.com/repos/langchain-ai/langchain/license)
- `langgraph==1.2.11` — [发布页](https://pypi.org/project/langgraph/1.2.11/) · [上游 LICENSE](https://api.github.com/repos/langchain-ai/langgraph/license)
- `langgraph-checkpoint==4.2.0` — [发布页](https://pypi.org/project/langgraph-checkpoint/4.2.0/) · [上游 LICENSE](https://api.github.com/repos/langchain-ai/langgraph/license)
- `langgraph-sdk==0.4.4` — [发布页](https://pypi.org/project/langgraph-sdk/0.4.4/) · [上游 LICENSE](https://api.github.com/repos/langchain-ai/langgraph/license)
- `openai==2.54.0` — [发布页](https://pypi.org/project/openai/2.54.0/) · [上游 LICENSE](https://api.github.com/repos/openai/openai-python/license)
- `pdfplumber==0.11.10` — [发布页](https://pypi.org/project/pdfplumber/0.11.10/) · [上游 LICENSE](https://api.github.com/repos/jsvine/pdfplumber/license)
- `Pillow==12.3.0` — [发布页](https://pypi.org/project/Pillow/12.3.0/) · [上游 LICENSE](https://api.github.com/repos/python-pillow/Pillow/license)
- `pymupdf==1.25.1` — [发布页](https://pypi.org/project/PyMuPDF/1.25.1/) · [上游 LICENSE](https://api.github.com/repos/pymupdf/PyMuPDF/license)
- `pypdf==6.16.2` — [发布页](https://pypi.org/project/pypdf/6.16.2/) · [上游 LICENSE](https://api.github.com/repos/py-pdf/pypdf/license)
- `pytesseract==0.3.13` — [发布页](https://pypi.org/project/pytesseract/0.3.13/) · [上游 LICENSE](https://api.github.com/repos/madmaze/pytesseract/license)
- `qdrant-client==1.12.1` — [发布页](https://pypi.org/project/qdrant-client/1.12.1/) · [上游 LICENSE](https://api.github.com/repos/qdrant/qdrant-client/license)
- `transformers==5.16.1` — [发布页](https://pypi.org/project/transformers/5.16.1/) · [上游 LICENSE](https://api.github.com/repos/huggingface/transformers/license)

### Development/test

- `coverage[toml]==7.16.0` — [发布页](https://pypi.org/project/coverage/7.16.0/) · [上游 LICENSE](https://api.github.com/repos/nedbat/coveragepy/license)
- `httpx==0.28.1` — [发布页](https://pypi.org/project/httpx/0.28.1/) · [上游 LICENSE](https://api.github.com/repos/encode/httpx/license)
- `mypy==1.14.0` — [发布页](https://pypi.org/project/mypy/1.14.0/) · [上游 LICENSE](https://api.github.com/repos/python/mypy/license)
- `pytest==9.1.1` — [发布页](https://pypi.org/project/pytest/9.1.1/) · [上游 LICENSE](https://api.github.com/repos/pytest-dev/pytest/license)
- `pytest-asyncio==1.4.0` — [发布页](https://pypi.org/project/pytest-asyncio/1.4.0/) · [上游 LICENSE](https://api.github.com/repos/pytest-dev/pytest-asyncio/license)
- `pytest-cov==7.1.0` — [发布页](https://pypi.org/project/pytest-cov/7.1.0/) · [上游 LICENSE](https://api.github.com/repos/pytest-dev/pytest-cov/license)
- `ruff==0.8.4` — [发布页](https://pypi.org/project/ruff/0.8.4/) · [上游 LICENSE](https://api.github.com/repos/astral-sh/ruff/license)

## Frontend 直接依赖

### Browser runtime

- `@ant-design/icons==6.3.2` — [发布页](https://www.npmjs.com/package/@ant-design/icons/v/6.3.2) · [上游 LICENSE](https://api.github.com/repos/ant-design/ant-design-icons/license)
- `@ant-design/x==2.9.0` — [发布页](https://www.npmjs.com/package/@ant-design/x/v/2.9.0) · [上游 LICENSE](https://api.github.com/repos/ant-design/x/license)
- `@tanstack/react-query==5.102.8` — [发布页](https://www.npmjs.com/package/@tanstack/react-query/v/5.102.8) · [上游 LICENSE](https://api.github.com/repos/TanStack/query/license)
- `antd==6.6.2` — [发布页](https://www.npmjs.com/package/antd/v/6.6.2) · [上游 LICENSE](https://api.github.com/repos/ant-design/ant-design/license)
- `react==19.2.8` — [发布页](https://www.npmjs.com/package/react/v/19.2.8) · [上游 LICENSE](https://api.github.com/repos/facebook/react/license)
- `react-dom==19.2.8` — [发布页](https://www.npmjs.com/package/react-dom/v/19.2.8) · [上游 LICENSE](https://api.github.com/repos/facebook/react/license)
- `react-markdown==10.1.0` — [发布页](https://www.npmjs.com/package/react-markdown/v/10.1.0) · [上游 LICENSE](https://api.github.com/repos/remarkjs/react-markdown/license)
- `react-router-dom==7.18.3` — [发布页](https://www.npmjs.com/package/react-router-dom/v/7.18.3) · [上游 LICENSE](https://api.github.com/repos/remix-run/react-router/license)
- `remark-gfm==4.0.1` — [发布页](https://www.npmjs.com/package/remark-gfm/v/4.0.1) · [上游 LICENSE](https://api.github.com/repos/remarkjs/remark-gfm/license)

### Development/test/build

- `@eslint/js==9.39.5` — [发布页](https://www.npmjs.com/package/@eslint/js/v/9.39.5) · [上游 LICENSE](https://api.github.com/repos/eslint/eslint/license)
- `@testing-library/dom==10.4.0` — [发布页](https://www.npmjs.com/package/@testing-library/dom/v/10.4.0) · [上游 LICENSE](https://api.github.com/repos/testing-library/dom-testing-library/license)
- `@testing-library/jest-dom==6.6.3` — [发布页](https://www.npmjs.com/package/@testing-library/jest-dom/v/6.6.3) · [上游 LICENSE](https://api.github.com/repos/testing-library/jest-dom/license)
- `@testing-library/react==16.3.3` — [发布页](https://www.npmjs.com/package/@testing-library/react/v/16.3.3) · [上游 LICENSE](https://api.github.com/repos/testing-library/react-testing-library/license)
- `@testing-library/user-event==14.6.6` — [发布页](https://www.npmjs.com/package/@testing-library/user-event/v/14.6.6) · [上游 LICENSE](https://api.github.com/repos/testing-library/user-event/license)
- `@types/node==20.17.10` — [发布页](https://www.npmjs.com/package/@types/node/v/20.17.10) · [上游 LICENSE](https://api.github.com/repos/DefinitelyTyped/DefinitelyTyped/license)
- `@types/react==19.0.3` — [发布页](https://www.npmjs.com/package/@types/react/v/19.0.3) · [上游 LICENSE](https://api.github.com/repos/DefinitelyTyped/DefinitelyTyped/license)
- `@types/react-dom==19.0.2` — [发布页](https://www.npmjs.com/package/@types/react-dom/v/19.0.2) · [上游 LICENSE](https://api.github.com/repos/DefinitelyTyped/DefinitelyTyped/license)
- `@vitejs/plugin-react==4.7.0` — [发布页](https://www.npmjs.com/package/@vitejs/plugin-react/v/4.7.0) · [上游 LICENSE](https://api.github.com/repos/vitejs/vite/license)
- `@vitest/coverage-v8==3.2.6` — [发布页](https://www.npmjs.com/package/@vitest/coverage-v8/v/3.2.6) · [上游 LICENSE](https://api.github.com/repos/vitest-dev/vitest/license)
- `autoprefixer==10.4.20` — [发布页](https://www.npmjs.com/package/autoprefixer/v/10.4.20) · [上游 LICENSE](https://api.github.com/repos/postcss/autoprefixer/license)
- `eslint==9.39.5` — [发布页](https://www.npmjs.com/package/eslint/v/9.39.5) · [上游 LICENSE](https://api.github.com/repos/eslint/eslint/license)
- `eslint-plugin-react-hooks==5.1.0` — [发布页](https://www.npmjs.com/package/eslint-plugin-react-hooks/v/5.1.0) · [上游 LICENSE](https://api.github.com/repos/facebook/react/license)
- `eslint-plugin-react-refresh==0.4.16` — [发布页](https://www.npmjs.com/package/eslint-plugin-react-refresh/v/0.4.16) · [上游 LICENSE](https://api.github.com/repos/ArnaudBarre/eslint-plugin-react-refresh/license)
- `globals==15.14.0` — [发布页](https://www.npmjs.com/package/globals/v/15.14.0) · [上游 LICENSE](https://api.github.com/repos/sindresorhus/globals/license)
- `jsdom==25.0.1` — [发布页](https://www.npmjs.com/package/jsdom/v/25.0.1) · [上游 LICENSE](https://api.github.com/repos/jsdom/jsdom/license)
- `postcss==8.5.26` — [发布页](https://www.npmjs.com/package/postcss/v/8.5.26) · [上游 LICENSE](https://api.github.com/repos/postcss/postcss/license)
- `prettier==3.4.2` — [发布页](https://www.npmjs.com/package/prettier/v/3.4.2) · [上游 LICENSE](https://api.github.com/repos/prettier/prettier/license)
- `tailwindcss==3.4.17` — [发布页](https://www.npmjs.com/package/tailwindcss/v/3.4.17) · [上游 LICENSE](https://api.github.com/repos/tailwindlabs/tailwindcss/license)
- `typescript==5.7.3` — [发布页](https://www.npmjs.com/package/typescript/v/5.7.3) · [上游 LICENSE](https://api.github.com/repos/microsoft/TypeScript/license)
- `typescript-eslint==8.46.2` — [发布页](https://www.npmjs.com/package/typescript-eslint/v/8.46.2) · [上游 LICENSE](https://api.github.com/repos/typescript-eslint/typescript-eslint/license)
- `vite==6.4.3` — [发布页](https://www.npmjs.com/package/vite/v/6.4.3) · [上游 LICENSE](https://api.github.com/repos/vitejs/vite/license)
- `vitest==3.2.6` — [发布页](https://www.npmjs.com/package/vitest/v/3.2.6) · [上游 LICENSE](https://api.github.com/repos/vitest-dev/vitest/license)

## 第三方 corpus 与内容边界

### Europe PMC 来源策略

`config/corpus_sources.json` 将 Europe PMC 配置为 provider，并记录其 REST 文档、版权页和隐私/条款入口：

- [Europe PMC REST documentation](https://europepmc.org/RestfulWebService)
- [Europe PMC Copyright](https://europepmc.org/Copyright)
- [Europe PMC Privacy Notice / terms entry](https://europepmc.org/PrivacyNotice)

工程配置只允许解析到以下 SPDX 字符串的候选记录：`CC0-1.0`、`CC-BY-2.0`、`CC-BY-2.5`、`CC-BY-3.0`、`CC-BY-4.0`。配置记录的许可入口为：

- [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/)
- [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/)
- [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

该 allowlist 只是自动化工程 gate：

- 不验证来源元数据是否准确或最新；
- 不替代逐条 attribution、notice、修改标识或其他义务；
- 不处理司法辖区、数据库权、隐私、商标、第三方素材等全部问题；
- 不表示项目将第三方文章重新许可为 MIT；
- 不保证每个 active 条目都适合重新分发或用于模型/评测。

发布元数据统计为 742 records、300 active、441 rejected、1 failed。数量只描述流水线状态，不是许可、医学质量或完整性结论。发行 corpus 前，operator 必须逐条保留 source URL、article ID、原始 license/provenance 与 attribution，并由有权限的人完成独立审查。

### Public eval

`public_eval/` 中签入的 6 条样本是项目自建 synthetic smoke set，manifest 标记为 MIT；它不含真实患者数据、私有答案、私有 object key 或 corpus-derived text。若本地生成 corpus 派生评测材料，只能放入 gitignored 的本地目录，并在获得明确发布许可前保持私有。

### 模型与外部服务

仓库中的模型名称、API adapter 和本地路径不等于模型权重随项目授权或分发。部署者必须分别审查模型权重、tokenizer、embedding/reranker、推理服务、API provider 的许可证、使用政策和数据处理条款。项目当前没有公开的真实 DeepSeek/其他模型验收或许可结论。