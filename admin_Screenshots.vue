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
              v-for="(emp, idx) in employees"
              :key="emp?.id || `emp-${idx}`"
              :label="emp?.name ? `${emp.name} (${emp.id})` : '加载中...'"
              :value="emp?.id || ''"
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

    <!-- 时间线滑块 -->
    <el-card v-if="screenshots.length > 0" class="timeline-bar" shadow="hover">
      <div class="timeline-header">
        <span class="timeline-title">时间线浏览</span>
        <span class="timeline-info"
          >{{ filteredScreenshots.length }} / {{ screenshots.length }} 张</span
        >
      </div>
      <el-slider
        v-model="timeFilter"
        :min="0"
        :max="23"
        :marks="timeMarks"
        @input="filterByTime"
      />
    </el-card>

    <!-- 截图网格 -->
    <el-card class="grid-card" shadow="hover">
      <div v-loading="loading" class="screenshot-grid">
        <el-empty
          v-if="filteredScreenshots.length === 0"
          description="暂无截图"
        />

        <div
          v-for="item in filteredScreenshots"
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
              <el-icon><Clock /></el-icon>
              <span>{{
                item.screenshot_time
                  ? dayjs(item.screenshot_time).format("HH:mm")
                  : "未知"
              }}</span>
            </div>
            <div class="info-row">
              <el-icon><User /></el-icon>
              <span>{{ item.computer_name || "未知" }}</span>
            </div>
            <div class="info-row">
              <el-icon><Document /></el-icon>
              <span>{{ formatFileSize(item.file_size) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="filteredScreenshots.length > 0" class="pagination">
        <el-pagination
          :current-page="currentPage"
          :page-size="pageSize"
          :page-sizes="[12, 24, 48, 96]"
          :total="filteredScreenshots.length"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handlePageChange"
          @current-change="handlePageChange"
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
            <el-descriptions-item label="员工">{{
              currentPreview?.employee_id
            }}</el-descriptions-item>
            <el-descriptions-item label="时间">{{
              currentPreview?.screenshot_time
                ? dayjs(currentPreview.screenshot_time).format(
                    "YYYY-MM-DD HH:mm:ss",
                  )
                : "未知"
            }}</el-descriptions-item>
            <el-descriptions-item label="计算机">{{
              currentPreview?.computer_name || "未知"
            }}</el-descriptions-item>
            <el-descriptions-item label="用户">{{
              currentPreview?.windows_user || "未知"
            }}</el-descriptions-item>
            <el-descriptions-item label="尺寸"
              >{{ currentPreview?.width }}x{{
                currentPreview?.height
              }}</el-descriptions-item
            >
            <el-descriptions-item label="大小">{{
              formatFileSize(currentPreview?.file_size)
            }}</el-descriptions-item>
            <el-descriptions-item label="格式">{{
              currentPreview?.format
            }}</el-descriptions-item>
            <el-descriptions-item label="加密">{{
              currentPreview?.encrypted ? "是" : "否"
            }}</el-descriptions-item>
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
// 格式化文件大小
const formatFileSize = (size) => {
  if (!size) return "0 B";
  if (size < 1024) return size + " B";
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
  return (size / (1024 * 1024)).toFixed(1) + " MB";
};
import { ref, computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import {
  Search,
  Refresh,
  Picture,
  Clock,
  User,
  Document,
  Lock,
  Download,
} from "@element-plus/icons-vue";
import { screenshotApi, employeeApi } from "./admin_api";
import dayjs from "dayjs";

const route = useRoute();
const loading = ref(false);
const employees = ref([]);
const screenshots = ref([]);
const filteredScreenshots = ref([]);
const currentPage = ref(1);
const pageSize = ref(24);
const timeFilter = ref(null);
const previewVisible = ref(false);
const previewFullscreen = ref(false);
const currentPreview = ref(null);

// 确保所有过滤器都有默认值
const filters = ref({
  employeeId: "",
  dateRange: [],
  startTime: "",
  endTime: "",
});

const timeMarks = {
  0: "00:00",
  6: "06:00",
  12: "12:00",
  18: "18:00",
  23: "23:00",
};

const previewTitle = computed(() => {
  if (!currentPreview.value) return "";
  return `截图预览 - ${currentPreview.value.employee_id} - ${currentPreview.value.datetime}`;
});

// 获取图片URL
// 获取图片URL
const getImageUrl = (path) => {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  const cleanPath = path.replace(/\\/g, "/");

  // 使用环境变量或当前域名
  const baseUrl = import.meta.env.VITE_API_BASE_URL
    ? import.meta.env.VITE_API_BASE_URL.replace("/api", "")
    : window.location.origin;

  return `${baseUrl}${cleanPath}`;
};
// 加载员工列表
const loadEmployees = async () => {
  try {
    const data = await employeeApi.getEmployees();
    employees.value = Array.isArray(data) ? data : [];
  } catch (error) {
    console.error("加载员工列表失败:", error);
    employees.value = [];
  }
};

// 加载截图
const loadScreenshots = async () => {
  loading.value = true;
  try {
    const params = {};

    if (filters.value.employeeId) {
      params.employee_id = filters.value.employeeId;
    }

    if (filters.value.dateRange && filters.value.dateRange.length === 2) {
      params.start_date = filters.value.dateRange[0] + " 00:00:00";
      params.end_date = filters.value.dateRange[1] + " 23:59:59";
    }

    const data = await screenshotApi.getScreenshots(params);
    screenshots.value = Array.isArray(data) ? data : [];
    applyTimeFilter();
  } catch (error) {
    console.error("加载截图失败:", error);
    ElMessage.error("加载截图失败");
    screenshots.value = [];
  } finally {
    loading.value = false;
  }
};

// 时间筛选
const filterByTime = () => {
  if (!screenshots.value || screenshots.value.length === 0) {
    filteredScreenshots.value = [];
    return;
  }

  if (timeFilter.value === null) {
    filteredScreenshots.value = screenshots.value;
  } else {
    filteredScreenshots.value = screenshots.value.filter((s) => {
      if (!s.time) return false;
      const hour = parseInt(s.time.split(":")[0]);
      return hour === timeFilter.value;
    });
  }
  currentPage.value = 1;
};

// 应用时间筛选
const applyTimeFilter = () => {
  filterByTime();
};

// 处理筛选变化
const handleFilterChange = () => {
  loadScreenshots();
};

// 重置筛选
const resetFilters = () => {
  filters.value = {
    employeeId: "",
    dateRange: [],
    startTime: "",
    endTime: "",
  };
  timeFilter.value = null;
  loadScreenshots();
};

// 分页处理
const handlePageChange = () => {
  // 分页逻辑由el-pagination自动处理
};

// 预览图片
const previewImage = (item) => {
  currentPreview.value = item;
  previewVisible.value = true;
};

// 下载图片
const downloadImage = () => {
  if (!currentPreview.value) return;

  const link = document.createElement("a");
  link.href = getImageUrl(currentPreview.value.url);
  link.download = currentPreview.value.filename;
  link.click();
};

// 监听路由参数
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

onMounted(() => {
  loadEmployees();
});
</script>

<style scoped>
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

.timeline-title {
  font-weight: 500;
  color: #333;
}

.timeline-info {
  font-size: 12px;
  color: #999;
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
