# RAW 图像格式支持 — 修改记录

## 背景

浏览器无法原生解码相机 RAW 文件（DNG、CR2、NEF、ARW 等），导致上传 RAW 图片后前端 `<img>` 无法显示。同时 PIL 也无法直接打开 RAW 文件，后端处理也需要适配。

本次改动通过引入 `rawpy` 库实现服务端 RAW→PNG 转换，并在前端检测 RAW 文件后请求服务端预览，从而完整支持 RAW 格式。

---

## 一、后端改动

### 1. `requirements.txt`

- **改动**：新增 `rawpy` 依赖
- **作用**：rawpy 是 LibRaw 的 Python 绑定，用于解码相机 RAW 文件

### 2. `api/file_bridge.py`

- **新增 rawpy 可选导入**：仿照 `pillow-heif` 的模式，try/except 导入 rawpy，设置 `HAS_RAW` 标志
- **新增 `RAW_EXTENSIONS` 集合**：`.dng`, `.cr2`, `.cr3`, `.nef`, `.arw`, `.orf`, `.rw2`, `.raf`, `.pef`, `.srw`, `.raw`
- **新增 `_decode_raw_to_pil()` 辅助函数**：用 rawpy 解码 RAW 字节 → PIL Image（RGB）
- **修改 `upload_to_ndarray()`**：检测 RAW 扩展名后走 rawpy 解码路径，而非 PIL
- **修改 `ensure_png_tempfile()`**：RAW 文件先解码为 PIL Image 再保存 PNG
- **修改 `_guess_media_type()`**：为 11 种 RAW 扩展名添加对应 MIME 类型映射

### 3. `api/routers/system.py`

- **新增 `POST /api/system/image-preview` 端点**：
  - 接收任意图片上传（包括 RAW/HEIC）
  - 调用 `ensure_png_tempfile()` 转为 PNG 临时文件
  - 用 PIL 获取尺寸
  - 注册到 `FileRegistry` 供前端通过 URL 访问
  - 返回 `{ preview_url, width, height }`

### 4. `core/image_preprocessor.py`

- **新增 rawpy 可选导入 + `RAW_EXTENSIONS` 集合**
- **修改 `SUPPORTED_FORMATS`**：加入所有 RAW 扩展名
- **修改 `detect_format()`**：RAW 文件通过扩展名检测（PIL 无法识别 RAW），缺少 rawpy 时抛出明确错误
- **修改 `get_image_dimensions()`**：RAW 文件用 rawpy 解码后从 ndarray shape 获取尺寸
- **修改 `convert_to_png()`**：RAW 文件经 rawpy → PIL → 保存 PNG
- **修改 `crop_image()`**：RAW 文件先解码为 PIL Image 再裁剪
- **修改 `process_upload()`**：RAW 格式也走 convert_to_png 路径

---

## 二、前端改动

### 5. `frontend/src/api/system.ts`

- **新增 `uploadImagePreview()` 函数**：
  - 将文件通过 `FormData` POST 到 `/api/system/image-preview`
  - 返回 `{ preview_url, width, height }`
  - 前端用返回的 URL 作为 `<img src>` 显示预览

### 6. `frontend/src/stores/extractorStore.ts`

- **新增 `RAW_EXTENSIONS` 集合 + `isRawFile()` 辅助函数**
- **修改 `setImageFile()`**：
  - 检测到 RAW 文件 → 调用 `uploadImagePreview()` 获取服务端 PNG 预览 URL
  - 非 RAW 文件 → 保持原有 `URL.createObjectURL()` 逻辑
  - blob URL 释放时仅对 `blob:` 前缀的 URL 调用 `revokeObjectURL`
- **新增 `rotateImage()` action**：
  - 通过 offscreen canvas 将当前预览图逆时针旋转 90°
  - 生成新的 blob URL 替换旧的
  - 自动清除角点（旋转后角点坐标失效）

### 7. `frontend/src/stores/converterStore.ts`

- **修改 `VALID_IMAGE_TYPES`**：添加 RAW MIME 类型
- **新增 `RAW_EXTENSIONS` 集合**
- **修改 `isValidImageType()`**：新增可选 `fileName` 参数，当 MIME 为空时回退到扩展名检测（浏览器对 RAW 文件可能报空 MIME）
- **修改 `ACCEPT_IMAGE_FORMATS`**：拼接 RAW 扩展名（`.dng,.cr2,...`）供 `<input accept>` 使用
- **修改 `setImageFile()`**：RAW 文件走服务端预览，与 extractorStore 同样逻辑
- **修改 `handleFilesSelect()`**：
  - 单文件时委托给 `setImageFile()`（已处理 RAW）
  - 验证调用传入 `file.name` 参数
- **修改 `addBatchFiles()`**：验证调用传入 `file.name`
- **修改 `removeBatchFile()`**：auto-downgrade 时委托给 `setImageFile()` 而非直接 `createObjectURL`

### 8. `frontend/src/components/ExtractorCanvas.tsx`

- **新增旋转按钮**：在 canvas 模式下，角点提示文字旁添加 `↺ 旋转` 按钮
- 使用已有翻译 key `ext_rotate_btn`
- 调用 store 的 `rotateImage()` action

---

## 三、测试改动

### 9. `frontend/src/__tests__/imageValidation.test.ts`

- **新增 "RAW files accepted by extension" 测试组**：11 个 RAW 扩展名的参数化测试，验证 `isValidImageType("", "photo.dng")` 等返回 `true`
- **更新 `ACCEPT_IMAGE_FORMATS` 长度断言**：从 6 → 17（6 MIME + 11 RAW 扩展名）

---

## 四、实现原理

```
用户上传 RAW 文件
       │
       ▼
前端检测扩展名 (.dng, .cr2, ...)
       │
       ├── 是 RAW → POST /api/system/image-preview
       │              │
       │              ▼
       │     后端 rawpy 解码 → PIL → PNG 临时文件
       │              │
       │              ▼
       │     返回 { preview_url, width, height }
       │              │
       │              ▼
       │     前端用 preview_url 作为 <img src> 显示
       │
       └── 非 RAW → URL.createObjectURL() (原有逻辑)
```

后端处理流程中，所有需要打开图片的地方（`upload_to_ndarray`、`ensure_png_tempfile`、`ImagePreprocessor` 的各方法）都增加了 RAW 扩展名检测分支，走 rawpy 解码路径。
