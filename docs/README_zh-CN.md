# ModuPort 中文入口

ModuPort 是面向多层框架模块化结构的力学型超单元分析与布局筛选软件。界面提供单模型静力/模态分析、50 × 50 footprint 绘制器、可行 H/V 模块布局枚举，以及 KX–KY、Pareto 前沿和均衡刚度布局查看。

## 使用

```bash
python -m pip install -e ".[ui]"
python -m streamlit run web/streamlit_app.py
```

在侧边栏选择“中文”。语言切换只影响显示，不修改结构输入、已绘制 footprint、求解结果或导出数据。计算仍采用 mm–N 单位制；E、G、Iy、Iz、KX、KY、Hz 等工程符号保持不变。安装、API、适用范围、限制和许可说明以英文主 [README](../README.md) 为准。
