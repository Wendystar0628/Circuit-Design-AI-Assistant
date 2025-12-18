# KaTeX Resources

本目录包含 KaTeX 数学公式渲染所需的资源文件。

## 当前版本

KaTeX v0.16.27

## 文件结构

```
katex/
├── katex.min.css       # 主样式表
├── katex.min.js        # 核心库
├── contrib/
│   └── auto-render.min.js  # 自动渲染扩展
└── fonts/              # 数学字体文件
    └── *.woff2         # Web 字体
```

## 使用方式

代码会自动检测本地 KaTeX 文件是否存在：
- 如果存在，使用本地 `file://` 协议加载
- 如果不存在，回退到 CDN 加载

## 更新步骤

1. 访问 https://github.com/KaTeX/KaTeX/releases
2. 下载最新版本的 zip 文件
3. 解压并替换本目录中的文件

## 许可证

KaTeX 使用 MIT 许可证。
https://github.com/KaTeX/KaTeX/blob/main/LICENSE
