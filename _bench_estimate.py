import numpy as np
import time
import sys

W, H = 800, 460
N = 64
L = 25

px_per_color = (W * H) // N

print("=== 逐色模拟新算法 ===")

# 模拟一个颜色的数据量
ys = np.random.randint(0, H, px_per_color)
xs = np.random.randint(0, W, px_per_color)

t0 = time.perf_counter()

all_keys = []
xs_left  = np.clip(xs - 1, 0, W - 1)
xs_right = np.clip(xs + 1, 0, W - 1)
ys_front = np.clip(ys - 1, 0, H - 1)
ys_near  = np.clip(ys + 1, 0, H - 1)

# 模拟TOP + BOTTOM
all_keys.append(np.column_stack([xs, ys, np.full(px_per_color, L, dtype=np.int32), np.zeros(px_per_color, dtype=np.uint8)]))
all_keys.append(np.column_stack([xs, ys, np.zeros(px_per_color, dtype=np.int32), np.ones(px_per_color, dtype=np.uint8)]))

# 模拟侧边
for z in range(L):
    l_ok = (xs == 0) | (ys >= 0)  # 简化
    if l_ok.any():
        all_keys.append(np.column_stack([xs[l_ok], ys[l_ok], np.full(l_ok.sum(), z, dtype=np.int32), np.full(l_ok.sum(), 2, dtype=np.uint8)]))

t1 = time.perf_counter()
print(f"侧边生成 + column_stack: {t1-t0:.2f}s")

keys = np.vstack(all_keys)
print(f"vstack: {keys.shape}, {t1-t0:.2f}s")

# unique
itemsize = keys.dtype.itemsize * keys.shape[1]
dt_void = np.dtype((np.void, itemsize))
t2 = time.perf_counter()
uniq = np.unique(keys.view(dt_void)).view(keys.dtype).reshape(-1, keys.shape[1])
t3 = time.perf_counter()
print(f"np.unique: {t3-t2:.2f}s, {len(uniq):,} 面")

# 向量生成顶点
CORNERS = np.array([
    [0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.],
    [0., 0., 1.], [1., 0., 1.], [1., 1., 1.], [0., 1., 1.],
], dtype=np.float64)
FC = np.array([
    [4, 5, 6, 7], [0, 3, 2, 1], [3, 7, 4, 0], [5, 6, 2, 1],
    [4, 5, 1, 0], [3, 7, 6, 2],
], dtype=np.intp)

n_faces = len(uniq)
px_arr = uniq[:, 0].astype(np.float64)
py_arr = uniq[:, 1].astype(np.float64)
pz_arr = uniq[:, 2].astype(np.float64)
ft_arr = uniq[:, 3].astype(np.int32)

t4 = time.perf_counter()
ci = FC[ft_arr]
corners = CORNERS[ci]
verts = np.zeros((n_faces, 4, 3), dtype=np.float64)
H_f = float(H)
ps = 0.1
LH = 0.08
verts[:, :, 0] = (px_arr[:, None] + corners[:, :, 0]) * ps
verts[:, :, 1] = (H_f - 1.0 - py_arr[:, None] + corners[:, :, 1]) * ps
verts[:, :, 2] = pz_arr[:, None] * LH
t5 = time.perf_counter()
print(f"向量顶点生成: {t5-t4:.2f}s")

# 三角形
t6 = time.perf_counter()
tris = np.zeros((n_faces * 2, 3), dtype=np.int32)
base = (np.arange(n_faces, dtype=np.int32) * 4)[:, None]
tris[0::2] = np.concatenate([base, base + 1, base + 2], axis=1)
tris[1::2] = np.concatenate([base, base + 2, base + 3], axis=1)
t7 = time.perf_counter()
print(f"三角形生成: {t7-t6:.2f}s")

total = t7 - t0
print(f"\n单色总计: {total:.2f}s")
print(f"64色估算: {total * 64:.1f}s")

print(f"\n=== 基准对比 ===")
print(f"旧版 mesh_loop: 1.58s")
print(f"新版单色: {total:.2f}s, 64色: {total*64:.1f}s")
