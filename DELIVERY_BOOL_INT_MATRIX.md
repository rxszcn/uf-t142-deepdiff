# 交付说明：布尔/整数差异在四类容器中的统一归类

## 一、问题现象

数仓对账两侧报文把标志位（Python `bool`）与计数（`int`）混用。由于 Python 中
`bool` 是 `int` 的子类，且 `True == 1`、`False == 0`（哈希也相等），同一个
“值相等但类型不同”的标量差异在四类容器里得到了四种互相矛盾的结果：

| 容器 | 改动前 `DeepDiff(左, 右)` 的输出 |
|------|--------------------------------|
| 保序列表 `[1]` vs `[True]` | `{}` —— 静默，无任何报告 |
| 字典 `{'a':1}` vs `{'a':True}` | `type_changes`（类型变更） |
| 忽略顺序的列表 `[1]` vs `[True]`（`ignore_order=True`） | `type_changes`（类型变更） |
| 集合 `{1}` vs `{True}` | `set_item_removed` + `set_item_added` 各一条（幽灵增删） |

## 二、三类根因

阅读了**哈希（`deephash.py`）、分发（`diff.py` 主 `_diff`）、列表对齐
（`diff.py` difflib / deephash 两条路径）**三块实现后，定位到根因有三处：

1. **保序列表静默 —— difflib 快速路径吞掉差异。**
   `_diff_ordered_iterable_by_difflib` 对“全基础可哈希序列”走
   `difflib.SequenceMatcher`。difflib 用 Python 原生值语义判等，
   `1 == True` 且 `hash(1) == hash(True)`，于是该段被标记为 `equal`，
   代码直接 `continue`，**永远不会递归进主分发 `_diff`**，类型差异因此丢失。

2. **集合幽灵增删 —— 纯哈希集合差，无配对、无递归。**
   `_diff_set` 直接对两侧 DeepHash 哈希键做集合差。而 DeepHash 在
   `_hash` 里把 `bool` 优先经 `_prep_bool` 预混成 `BoolObj` 枚举
   （`bool:true` / `bool:false`），`int` 则走 `_prep_number` 得到 `int:1`，
   两者哈希不同。于是同一个 Python 相等值同时落进“新增”和“删除”两个桶，
   被当作一删一增报告。

3. **字典 / 忽略顺序列表本身是正确基准。**
   字典逐键递归、忽略顺序列表在哈希配对后也会递归，二者最终都进入主分发
   `_diff`，由 `get_type` 区分 `bool` 与 `int`，经 `_diff_types` 报告
   `type_changes`。这条路径的行为被保留为统一口径的基准。

## 三、统一后的归类口径与呈现形态

### 归类：四类容器一律归为 `type_changes`

统一向根因 3 的既有正确行为看齐。理由：

- **DeepHash 本就把 bool 与 int 视为不同对象**（`BoolObj` vs `int:n`），
  归为类型变更与哈希层“二者不同”的既有约定一致，不需要改动任何哈希约定；
- 字典与忽略顺序列表此前已经这样报告，统一后这两类**零行为变化**，不产生回退；
- `type_changes` 能同时携带 `old_type/new_type/old_value/new_value` 四元信息，
  对账方可以明确区分“标志位变成了计数”而非普通的值变化，信息量高于
  `values_changed`，也避免了集合幽灵增删带来的“凭空多一条/少一条”误导。

### 变更值的呈现形态

- **可下标容器（列表、字典）**：沿用原路径，如 `root[0]`、`root['a']`，
  载荷为标准 `type_changes` 四元组。
- **集合 / frozenset**：集合元素没有下标，沿用集合既有的
  `set_item_added/removed` 的 `root[值]` 寻址约定，以 t1 元素值作为路径锚点，
  例如 `{1} → {True}` 报告为
  `type_changes: root[1] -> {old_type:int, new_type:bool, old_value:1, new_value:True}`，
  tree/delta 视图中 `new_path` 为 `root[True]`。实现上用
  `SubscriptableIterableRelationship` 携带元素值作为 param。

统一后（默认参数）：

```text
[1]  vs [True]   -> type_changes root[0]   int -> bool, 1 -> True
{a:1} vs {a:True}-> type_changes root['a'] int -> bool, 1 -> True
[1] vs [True](IO)-> type_changes root[0]   int -> bool, 1 -> True
{1}  vs {True}   -> type_changes root[1]   int -> bool, 1 -> True
```

### 与 `ignore_numeric_type_changes` 的协同

DeepHash 对 bool 的预混发生在数字处理之前，因此即使设置
`ignore_numeric_type_changes=True`，bool/int 的哈希仍然不同，集合与忽略顺序
路径依旧会产生差异。为恢复该开关“忽略数值类类型变更”的文档语义，在主分发
`_diff` 入口增加一道守卫：当开关打开、且两侧是值相等的 bool/int 配对时，
直接判定为无差异。四类容器在此开关下统一输出 `{}`。

## 四、具体改动

| 文件 | 改动 |
|------|------|
| `deepdiff/helper.py` | 新增 `numpy_integer_types = (np.integer,)`（无 numpy 时为空元组），用于精确刻画整型侧边界 |
| `deepdiff/diff.py` | 1. 新增静态谓词 `_is_bool_int_mismatch`：bool/整型边界的唯一定义；<br>2. 新增 `_bool_int_type_change_ignored`：承载忽略开关的语义；<br>3. 主分发 `_diff` 入口加入忽略守卫；<br>4. difflib `equal` 分支对 bool/int 错位重新递归主分发（修根因 1）；<br>5. `_diff_set` 对值相等的 bool/int 项一对一配对后递归主分发，真差异仍走增删（修根因 2） |

### 边界的刻意收窄

谓词只匹配“恰有一侧是布尔（Python `bool` 或 numpy `np.bool_`），另一侧是整型
（Python `int` 或 numpy 整型）”的组合，**明确排除 `float`**（如 `True` vs
`1.0` 维持原有集合增删行为），从而把影响面严格限制在本任务的布尔/整数边界，
不触碰字符串、普通数值、真类型差异等既有行为。

## 五、不回退的既有约定（已逐一验证）

- **真类型差异**：`{1} vs {'1'}` 仍报 `set_item_removed/added`；
- **字符串差异**：`['a'] vs ['b']` 仍报 `values_changed`；
- **普通数值差异**：`[1] vs [2]` 仍报 `values_changed`；
- **纯布尔值变**：`[True] vs [False]` 仍报 `values_changed`；
- **哈希与相等性约定**：未改动 `deephash.py` 任何哈希逻辑，bool 仍预混为
  `BoolObj`、int 仍走数字路径，二者哈希依旧不同；Python `==`/`hash` 语义不变；
- **值不等的 bool/int**：`{True} vs {2}` 因 `True != 2` 不构成配对，仍报增删。

## 六、测试

新增 `tests/test_bool_int_matrix.py`（54 个用例），四态矩阵覆盖：

1. **四容器 × 两方向 × 两组值（1/True、0/False）**：默认参数下统一 `type_changes`；
2. 四容器归类与值载荷逐字节一致的对照断言；
3. 集合不再产生幽灵增删、多对 bool/int 一对一配对、真增删与类型变更混合场景；
4. `ignore_numeric_type_changes=True` 下四容器（含 frozenset、ignore_order）统一 `{}`；
5. 不回退矩阵：纯布尔值变、真类型差异、值不等 bool/int、float 排除、字符串、
   普通数值、相等对象、tuple、嵌套容器；
6. 谓词本身的单元测试（含 numpy 整型、对称性）。

全量结果：**1315 passed, 45 skipped**。另有 2 个失败/错误在改动前的干净
HEAD 上同样存在，与本次改动无关：

- `test_security.py::test_remote_code_execution`：测试硬编码期望 `posix.system`，
  Windows 平台实际为 `nt.system`；
- `test_summarize.py::test_nested_structure_summary2`：测试以 GBK 读取含
  非 ASCII 字节的 JSON 文件触发 `UnicodeDecodeError`。

## 七、已知的既有局限（未在本次范围内修改）

`DeepHash(np.bool_(True))[np.bool_(True)]` 的顶层标量查找会 KeyError——
`DeepHash._getitem` 只识别 Python 单例 `True/False`（`np.True_ is True` 为假）。
这导致 numpy `np.bool_` 作为**集合元素**时在 hashtable 构建阶段就被跳过，
本次集合配对无法覆盖该组合（Python `bool` 与 numpy 整型的组合不受影响）。
这是 DeepHash 查找层的独立缺陷，超出“布尔/整数标志位对账”任务范围，未顺手扩大
改动面，建议另开任务处理。
