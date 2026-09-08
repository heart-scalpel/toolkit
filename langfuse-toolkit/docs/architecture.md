# 代码分层

命令按资源归属分层；鉴权方式与资源归属分别管理。

```text
app/
  cli.py                 参数适配、删除确认、JSON 输出
  command_parser.py      instance / org / project / workflow 命令定义
  application.py         输入预校验、凭据预检、操作分发；返回数据
  runtime.py             按需组装各层客户端与服务
  core/                  配置、命令数据、HTTP、会话、通用校验
  instance/              实例健康检查，无鉴权
  organizations/         组织内项目列表，组织 API Key
  projects/              项目资源与项目 ID 校验，项目 API Key
    prompts.py           Prompt 版本与标签维护
    prompt_definitions.py 本地 Prompt 定义加载
    catalog.py           资源与支持的操作
    queries.py           ResourceRequest → API 请求
    validation.py        写入内容校验
    resources.py         请求执行、分页、写后核对
    llms.py              模型连接查询
    playground.py        编译输入，组合项目读取与会话执行
  workflows/             顺序执行已校验的操作，汇总结果
```

依赖方向是 `CLI → application/runtime → 各业务层 → core`。业务层不依赖命令行解析，不打印或读取终端；工作流接收操作返回值，不捕获终端输出。

四种连接各自持有 HTTP 客户端：实例无鉴权、组织 Basic Auth、项目 Basic Auth、用户会话 Cookie。项目资源访问前检查密钥所属项目；组织密钥不代替项目密钥。Playground 属于项目功能，执行时额外组合会话客户端。

扩展普通项目资源时更新 `projects/catalog.py` 和对应查询/校验；复杂功能放在独立项目服务。新增组织能力放在 `organizations/`，由应用层连接命令。跨层流程放在 `workflows/`，不要让组织或项目层互相调用。
