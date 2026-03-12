<template>
  <div class="screenshots">
    <!-- 筛选栏 -->
    <el-card class="filter-bar" shadow="hover">
      <el-row :gutter="20" align="middle">
        <el-col :span="6">
          <el-select
            v-model="filters.employeeId"
            placeholder="选择员工"
            clearable
            filterable
            @change="handleFilterChange"
          >
            <el-option
              v-for="emp in employees"
              :key="emp.employee_id || emp.id"
              :label="
                emp.name
                  ? `${emp.name} (${emp.employee_id || emp.id})`
                  : '加载中...'
              "
              :value="emp.employee_id || emp.id"
            />
          </el-select>
        </el-col>

        <el-col :span="6">
          <el-date-picker
            v-model="filters.dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            @change="handleFilterChange"
            :model-value="filters.dateRange || []"
          />
        </el-col>

        <el-col :span="4">
          <el-time-select
            v-model="filters.startTime"
            placeholder="开始时间"
            start="00:00"
            step="01:00"
            end="23:00"
            @change="handleFilterChange"
            :model-value="filters.startTime || ''"
          />
        </el-col>

        <el-col :span="4">
          <el-time-select
            v-model="filters.endTime"
            placeholder="结束时间"
            start="00:00"
            step="01:00"
            end="23:00"
            @change="handleFilterChange"
            :model-value="filters.endTime || ''"
          />
        </el-col>

        <el-col :span="4" class="text-right">
          <el-button type="primary" @click="loadScreenshots">
            <el-icon><Search /></el-icon>查询
          </el-button>
          <el-button @click="resetFilters">
            <el-icon><Refresh /></el-icon>重置
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- 时间线滑块（现在控制后端时间筛选） -->
    <el-card v-if="total > 0" class="timeline-bar" shadow="hover">
      <div class="timeline-header">
        <div class="timeline-title-section">
          <span class="timeline-title">时间线浏览</span>
          <el-tag
            v-if="timeFilter !== null"
            type="warning"
            size="small"
            effect="light"
            class="time-filter-active"
          >
            <el-icon><Timer /></el-icon>
            筛选: {{ formatHour(timeFilter) }}
            <el-icon @click.stop="clearTimeFilter" class="clear-filter"
              ><Close
            /></el-icon>
          </el-tag>
        </div>
        <span class="timeline-info"
          >{{ screenshots.length }} / {{ total }} 张</span
        >
      </div>
      <el-slider
        v-model="timeFilter"
        :min="0"
        :max="23"
        :marks="timeMarks"
        @input="handleTimeFilterChange"
      />
    </el-card>

    <!-- 截图网格 -->
    <el-card class="grid-card" shadow="hover">
      <div v-loading="loading" class="screenshot-grid">
        <el-empty v-if="screenshots.length === 0" description="暂无截图" />

        <div
          v-for="item in screenshots"
          :key="item.id"
          class="screenshot-item"
          @click="previewImage(item)"
        >
          <div class="screenshot-image">
            <el-image
              :src="getImageUrl(item.thumbnail || item.storage_url)"
              fit="cover"
              loading="lazy"
              :preview-src-list="[getImageUrl(item.storage_url)]"
              :preview-teleported="true"
              @click.stop
            >
              <template #error>
                <div class="image-error">
                  <el-icon><Picture /></el-icon>
                </div>
              </template>
            </el-image>
            <div v-if="item.encrypted" class="encrypted-badge">
              <el-icon><Lock /></el-icon>
            </div>
          </div>
          <div class="screenshot-info">
            <div class="info-row">
              <el-icon><User /></el-icon>
              <span class="employee-name" :title="`ID: ${item.employee_id}`">
                {{ getEmployeeName(item) }}
              </span>
            </div>
            <div class="info-row">
              <el-icon><Clock /></el-icon>
              <span>{{ formatTime(item.screenshot_time) }}</span>
            </div>
            <div class="info-row">
              <el-icon><Monitor /></el-icon>
              <span>{{ item.computer_name || "未知" }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="total > 0" class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[12, 24, 48, 96]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </el-card>

    <!-- 图片预览对话框 -->
    <el-dialog
      v-model="previewVisible"
      :title="previewTitle"
      width="80%"
      :fullscreen="previewFullscreen"
      destroy-on-close
    >
      <div class="preview-container">
        <el-image
          :src="getImageUrl(currentPreview?.storage_url)"
          fit="contain"
          class="preview-image"
          :preview-teleported="true"
          :initial-index="0"
        />

        <div class="preview-info">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="员工姓名">
              <div>
                <strong>{{ getEmployeeName(currentPreview) }}</strong>
                <span style="color: #999; margin-left: 8px; font-size: 12px">
                  ID: {{ currentPreview?.employee_id }}
                </span>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="计算机">
              {{ currentPreview?.computer_name || "未知" }}
            </el-descriptions-item>
            <el-descriptions-item label="时间">
              {{ formatFullDateTime(currentPreview?.screenshot_time) }}
            </el-descriptions-item>
            <el-descriptions-item label="用户">
              {{ currentPreview?.windows_user || "未知" }}
            </el-descriptions-item>
            <el-descriptions-item label="尺寸">
              {{ currentPreview?.width }}x{{ currentPreview?.height }}
            </el-descriptions-item>
            <el-descriptions-item label="大小">
              {{ formatFileSize(currentPreview?.file_size) }}
            </el-descriptions-item>
            <el-descriptions-item label="格式">
              {{ currentPreview?.format }}
            </el-descriptions-item>
            <el-descriptions-item label="加密">
              {{ currentPreview?.encrypted ? "是" : "否" }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </div>

      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
        <el-button type="primary" @click="downloadImage">
          <el-icon><Download /></el-icon>下载
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// ===== 导入统一的时间工具 =====
import {
  formatTime,
  formatFullDateTime,
  formatFileSize as formatFileSizeUtil,
  getHour,
} from "./admin_timezone";
// ============================

import { ref, computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import {
  Search,
  Refresh,
  Picture,
  Clock,
  User,
  Monitor,
  Lock,
  Download,
  Timer,
  Close,
} from "@element-plus/icons-vue";
import { screenshotApi, employeeApi } from "./admin_api";

// ===== 使用统一的文件大小格式化函数 =====
const formatFileSize = formatFileSizeUtil;
// ====================================

const route = useRoute();
const loading = ref(false);
const employees = ref([]);
// ===== 创建员工姓名映射表 =====
const employeeNameMap = ref(new Map());
// ============================

// ✅ 简化：只保留 screenshots，移除 filteredScreenshots
const screenshots = ref([]); // 直接从API返回的数据
const currentPage = ref(1);
const pageSize = ref(24);
const timeFilter = ref(null);
const previewVisible = ref(false);
const previewFullscreen = ref(false);
const currentPreview = ref(null);
const total = ref(0); // 总记录数（来自API）

// 确保所有过滤器都有默认值
// 确保所有过滤器都有默认值
const filters = ref({
  employeeId: "",
  dateRange: [],
  startTime: "",
  endTime: "",
  start_date: undefined,
  end_date: undefined,
});

const timeMarks = {
  0: "00:00",
  6: "06:00",
  12: "12:00",
  18: "18:00",
  23: "23:00",
};

// ===== ✅ 简化：后端已分页，直接返回 =====
const paginatedScreenshots = computed(() => screenshots.value);

// ===== 预览标题使用员工姓名 =====
const previewTitle = computed(() => {
  if (!currentPreview.value) return "";
  const employeeName = getEmployeeName(currentPreview.value);
  return `截图预览 - ${employeeName} - ${currentPreview.value.datetime}`;
});

// ===== 格式化小时显示 =====
const formatHour = (hour) => {
  return `${hour.toString().padStart(2, "0")}:00 - ${hour.toString().padStart(2, "0")}:59`;
};

// ===== 获取员工姓名的函数 =====
const getEmployeeName = (item) => {
  if (!item || !item.employee_id) return "未知员工";

  // 1. 优先使用后端返回的 name 字段
  if (item.name) {
    return item.name;
  }

  // 2. 其次使用映射表中的姓名（兼容旧数据）
  const name = employeeNameMap.value.get(item.employee_id);
  return name || item.employee_id;
};

// 获取图片URL
const getImageUrl = (path) => {
  if (!path) return "";
  if (path.startsWith("http")) return path;

  // 处理Windows路径分隔符
  const cleanPath = path.replace(/\\/g, "/");

  // 使用当前域名
  const baseUrl = window.location.origin;

  let finalUrl;
  if (cleanPath.startsWith("/screenshots/")) {
    finalUrl = `${baseUrl}${cleanPath}`;
  } else {
    finalUrl = `${baseUrl}/screenshots${cleanPath.startsWith("/") ? "" : "/"}${cleanPath}`;
  }

  // ✅ 添加调试日志（只打印前几个，避免刷屏）
  if (Math.random() < 0.01) {
    // 1%的概率打印，避免日志太多
    console.log("图片URL转换:", {
      original: path,
      cleanPath: cleanPath,
      finalUrl: finalUrl,
    });
  }

  return finalUrl;
};

// ===== 加载员工列表并建立映射 =====
const loadEmployees = async () => {
  try {
    const response = await employeeApi.getEmployees({ limit: 1000 });

    // 处理返回数据
    if (response && response.items) {
      employees.value = response.items;
    } else if (Array.isArray(response)) {
      employees.value = response;
    } else {
      employees.value = [];
    }

    // 建立员工ID到姓名的映射
    employeeNameMap.value.clear();
    employees.value.forEach((emp) => {
      // 注意：后端返回的ID字段可能是 employee_id 或 id
      const empId = emp.employee_id || emp.id;
      if (empId && emp.name) {
        employeeNameMap.value.set(empId, emp.name);
        console.log(`员工映射: ${empId} -> ${emp.name}`); // 调试日志
      }
    });

    console.log("员工列表:", employees.value); // 调试日志
    console.log("员工映射表已建立，共", employeeNameMap.value.size, "条记录");
  } catch (error) {
    console.error("加载员工列表失败:", error);
    employees.value = [];
  }
};

// ===== ✅ 核心：加载截图列表（完全依赖后端分页）=====
const loadScreenshots = async () => {
  loading.value = true;
  try {
    const params = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
    };

    // 员工筛选
    if (filters.value.employeeId) {
      params.employee_id = filters.value.employeeId;
    }

    // ===== 修复：优先使用时间滑块设置的日期 =====
    if (filters.value.start_date && filters.value.end_date) {
      // 时间滑块已经设置好了完整的日期时间
      params.start_date = filters.value.start_date;
      params.end_date = filters.value.end_date;
      console.log("使用时间滑块日期:", params.start_date, params.end_date);
    }
    // 否则使用日期范围和时间选择器
    else if (filters.value.dateRange && filters.value.dateRange.length === 2) {
      const startDate = filters.value.dateRange[0];
      const endDate = filters.value.dateRange[1];

      // 如果有具体时间，组合使用
      if (filters.value.startTime) {
        params.start_date = `${startDate} ${filters.value.startTime}:00`;
      } else {
        params.start_date = `${startDate} 00:00:00`;
      }

      if (filters.value.endTime) {
        params.end_date = `${endDate} ${filters.value.endTime}:59`;
      } else {
        params.end_date = `${endDate} 23:59:59`;
      }
      console.log("使用日期时间筛选:", params.start_date, params.end_date);
    } else {
      // 没有日期范围，只有时间筛选
      if (filters.value.startTime) {
        params.start_time = filters.value.startTime;
      }
      if (filters.value.endTime) {
        params.end_time = filters.value.endTime;
      }
      console.log("使用时间筛选:", params.start_time, params.end_time);
    }

    console.log("最终请求参数:", params);
    const response = await screenshotApi.getScreenshots(params);
    console.log("API返回状态:", {
      hasItems: !!response?.items,
      total: response?.total,
      itemCount: response?.items?.length,
    });

    // 处理返回数据
    if (response && typeof response === "object") {
      if (response.items) {
        screenshots.value = response.items;
        total.value = response.total || 0;

        // ✅ 添加调试：检查第一张图片的加载
        if (screenshots.value.length > 0) {
          const firstItem = screenshots.value[0];
          const imageUrl = getImageUrl(firstItem.storage_url || firstItem.url);

          console.log("第一张图片详细信息:", {
            id: firstItem.id,
            employee_id: firstItem.employee_id,
            name: firstItem.name,
            storage_url: firstItem.storage_url,
            url: firstItem.url,
            thumbnail: firstItem.thumbnail,
            imageUrl: imageUrl,
          });

          // 测试图片是否可加载
          const img = new Image();
          img.onload = () => {
            console.log("✅ 图片加载成功:", {
              url: imageUrl,
              width: img.width,
              height: img.height,
            });
          };
          img.onerror = (e) => {
            console.error("❌ 图片加载失败:", {
              url: imageUrl,
              error: e,
              status: e?.target?.status,
            });

            // 尝试备用URL
            if (firstItem.thumbnail) {
              const thumbUrl = getImageUrl(firstItem.thumbnail);
              console.log("尝试加载缩略图:", thumbUrl);
              const thumbImg = new Image();
              thumbImg.onload = () =>
                console.log("✅ 缩略图加载成功:", thumbUrl);
              thumbImg.onerror = () =>
                console.error("❌ 缩略图也加载失败:", thumbUrl);
              thumbImg.src = thumbUrl;
            }
          };
          img.src = imageUrl;
        } else {
          console.log("没有截图数据");
        }
      } else if (Array.isArray(response)) {
        screenshots.value = response;
        total.value = screenshots.value.length;
        console.log("返回数组格式，长度:", screenshots.value.length);
      } else {
        screenshots.value = [];
        total.value = 0;
        console.warn("API返回格式异常:", response);
      }
    } else {
      screenshots.value = [];
      total.value = 0;
      console.warn("API返回为空或格式错误:", response);
    }
  } catch (error) {
    console.error("加载截图失败:", {
      error: error,
      message: error.message,
      response: error.response?.data,
    });
    ElMessage.error(
      "加载截图失败: " + (error.response?.data?.detail || error.message),
    );
    screenshots.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
    console.log("加载完成，当前截图数量:", screenshots.value.length);
  }
};

// ===== ✅ 处理时间筛选变化 =====
const handleTimeFilterChange = () => {
  if (timeFilter.value === null) {
    // 清除时间筛选时，恢复到完整的日期范围
    if (filters.value.dateRange && filters.value.dateRange.length === 2) {
      filters.value.start_date = filters.value.dateRange[0] + " 00:00:00";
      filters.value.end_date = filters.value.dateRange[1] + " 23:59:59";
    } else {
      // 如果没有日期范围，设置为 undefined
      filters.value.start_date = undefined;
      filters.value.end_date = undefined;
    }
  } else {
    const hour = timeFilter.value.toString().padStart(2, "0");

    if (filters.value.dateRange && filters.value.dateRange.length === 2) {
      // 有日期范围：合并日期和时间
      filters.value.start_date = `${filters.value.dateRange[0]} ${hour}:00:00`;
      filters.value.end_date = `${filters.value.dateRange[1]} ${hour}:59:59`;
    } else {
      // 没有日期范围：使用当前日期
      const today = new Date().toISOString().split("T")[0];
      filters.value.start_date = `${today} ${hour}:00:00`;
      filters.value.end_date = `${today} ${hour}:59:59`;
    }
  }
  currentPage.value = 1;
  loadScreenshots();
};

// ===== 清除时间筛选 =====
const clearTimeFilter = () => {
  timeFilter.value = null;
  filters.value.startTime = "";
  filters.value.endTime = "";
  currentPage.value = 1;
  loadScreenshots();
};

// ===== 处理筛选变化 =====
const handleFilterChange = () => {
  currentPage.value = 1;
  // 清除时间筛选滑块
  timeFilter.value = null;
  filters.value.startTime = "";
  filters.value.endTime = "";
  // 清除时间滑块的日期设置
  filters.value.start_date = undefined;
  filters.value.end_date = undefined;
  loadScreenshots();
};

// ===== 重置筛选 =====
const resetFilters = () => {
  filters.value = {
    employeeId: "",
    dateRange: [],
    startTime: "",
    endTime: "",
    start_date: undefined,
    end_date: undefined,
  };
  timeFilter.value = null;
  currentPage.value = 1;
  loadScreenshots();
};

// ===== ✅ 简化：翻页都重新加载数据 =====
const handleCurrentChange = (val) => {
  currentPage.value = val;
  loadScreenshots();
};

// ===== ✅ 简化：分页大小变化也重新加载 =====
const handleSizeChange = (val) => {
  pageSize.value = val;
  currentPage.value = 1;
  loadScreenshots();
};

// ===== 预览图片 =====
const previewImage = (item) => {
  currentPreview.value = item;
  previewVisible.value = true;
};

// ===== 下载图片 =====
const downloadImage = () => {
  if (!currentPreview.value) return;

  const link = document.createElement("a");
  link.href = getImageUrl(currentPreview.value.storage_url);
  link.download = currentPreview.value.filename || "screenshot.jpg";
  link.click();
};

// ===== 监听路由参数 =====
watch(
  () => route.query,
  (query) => {
    if (query.employee_id) {
      filters.value.employeeId = query.employee_id;
      loadScreenshots();
    }
  },
  { immediate: true },
);

// ===== 监听筛选条件变化 =====
watch(
  () => [filters.value.employeeId, filters.value.dateRange],
  () => {
    loadScreenshots();
  },
  { deep: true },
);

onMounted(() => {
  loadEmployees();
});
</script>

<style scoped>
/* 样式保持不变 */
.screenshots {
  padding: 20px;
}

.filter-bar {
  margin-bottom: 20px;
}

.timeline-bar {
  margin-bottom: 20px;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.timeline-title-section {
  display: flex;
  align-items: center;
  gap: 12px;
}

.timeline-title {
  font-weight: 500;
  color: #333;
}

.timeline-info {
  font-size: 12px;
  color: #999;
}

.time-filter-active {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.clear-filter {
  cursor: pointer;
  margin-left: 4px;
  font-size: 12px;
}

.clear-filter:hover {
  color: #f56c6c;
}

.grid-card {
  min-height: 500px;
}

.screenshot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 20px;
  padding: 10px;
}

.screenshot-item {
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  transition: all 0.3s;
  cursor: pointer;
}

.screenshot-item:hover {
  transform: translateY(-5px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
}

.screenshot-image {
  position: relative;
  width: 100%;
  height: 160px;
  overflow: hidden;
  background: #f5f5f5;
}

.screenshot-image :deep(.el-image) {
  width: 100%;
  height: 100%;
}

.screenshot-image :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-error {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 32px;
  background: #f5f5f5;
}

.encrypted-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  gap: 4px;
}

.screenshot-info {
  padding: 12px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-row .el-icon {
  font-size: 14px;
  color: #999;
}

/* 员工姓名样式 */
.employee-name {
  font-weight: 500;
  color: #409eff;
  cursor: help;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pagination {
  margin-top: 20px;
  text-align: right;
}

.text-right {
  text-align: right;
}

/* 预览对话框 */
.preview-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.preview-image {
  width: 100%;
  max-height: 60vh;
  object-fit: contain;
  background: #f5f5f5;
  border-radius: 8px;
}

.preview-info {
  padding: 20px;
  background: #f8f9fa;
  border-radius: 8px;
}
</style>
