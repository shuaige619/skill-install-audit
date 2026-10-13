# Skill 安装文件核对

安装或迁移 Skill 后，将目标目录与自己确认的参考版本逐文件核对，找出缺失、改动和额外文件。全程只读，不自动修复。

`skill-install-audit` · 原创 Skill · 内容版本 `9e745e834d9b`

## 适用场景

将指定的已安装 Skill 目录与用户确认的参考版本进行只读文件核对，报告缺失、改动和额外文件。用于安装后核对、副本一致性和迁移检查；不用于自动更新、安装修复、恶意代码审计或证明宿主已加载技能。

## 安装与使用

```sh
git clone https://github.com/shuaige619/skill-install-audit.git
cd skill-install-audit
```

将此目录按宿主支持的方式登记为本地 Skill，或把 [SKILL.md](SKILL.md) 交给支持 Agent Skills 的助手读取。保留 `scripts/`、`references/` 等配套目录的相对位置；下载完成不代表宿主已加载。

Python 3.10+，只使用标准库。可以直接运行脚本，也可以由能执行本地 Python 的 Agent 调用。

## 输入与输出

**输入：** 参考 Skill 目录（或已冻结的参考清单）、待核对的安装目录，以及一个新的输出目录。

**输出：** audit.json（完整记录）、report.md（可读报告）和 files.csv（逐文件明细）。

## 使用示例

```text
请使用 skill-install-audit，将 ./reference-skill 冻结为 ./reference-manifest.json，再核对 ./installed-skill，结果写到新的 ./audit-result 目录。解释差异，不要修改任何被核对的文件。
```

以上是调用示例，不是已完成业务运行的记录。

## 工作方式

执行步骤、判断规则和交付标准见 [SKILL.md](SKILL.md)。

- [references/contract.md](references/contract.md)

## 验证与限制

原项目记录包含 23 项程序检查与 3 次 WorkBuddy 原生任务。发布环节不把这些历史检查视为对新字节的重新验证；首次 GitHub 发布另对相同 Skill 字节执行现有程序检查。

check 退出码 0 表示一致，2 表示核对成功且发现差异，1 表示输入或执行失败。文件一致不证明参考最新、安全、业务正确或宿主已加载。

## 来源与二创说明

本项目原创；按明确的参考版本做只读文件核对。

文件身份与发布标准版本记录在 [发布清单](skill-release.json) 中。问题反馈请附复现输入、期望结果及内容版本，并先移除私人数据。

## 许可证

以仓库随附的 LICENSE / NOTICE 为准；未附许可证的部分尚未授予额外使用许可，请联系作者。
