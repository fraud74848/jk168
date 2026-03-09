<template>
  <div class="clients">
    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-content">
            <div class="stat-icon" style="background: #e6f7ff; color: #1890ff">
              <el-icon :size="24"><Monitor /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ totalClients }}</div>
              <div class="stat-label">总客户端数</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-content">
            <div class="stat-icon" style="background: #f6ffed; color: #52c41a">
              <el-icon :size="24"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ onlineClients }}</div>
              <div class="stat-label">在线客户端</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-content">
            <div class="stat-icon" style="background: #fff7e6; color: #fa8c16">
              <el-icon :size="24"><Clock /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ offlineClients }}</div>
              <div class="stat-label">离线客户端</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 客户端列表 -->
    <el-card class="table-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>客户端列表</span>
          <el-switch
            v-model="showOnlineOnly"
            active-text="仅显示在线"
            inactive-text="全部"
            @change="loadClients"
          />
        </div>
      </template>

      <el-table v-loading="loading" :data="clients" stripe style="width: 100%">
        <el-table-column type="index" width="50" />

        <el-table-column label="客户端ID" min-width="200">
          <template #default="{ row }">
            <div class="client-info">
              <el-tag
                :type="row.is_online ? 'success' : 'info'"
                size="small"
                effect="dark"
                circle
              >
                ●
              </el-tag>
              <span class="client-id">{{ row.client_id }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="计算机名" width="150">
          <template #default="{ row }">
            {{ row.computer_name || "-" }}
          </template>
        </el-table-column>

        <el-table-column label="Windows用户" width="150">
          <template #default="{ row }">
            {{ row.windows_user || "-" }}
          </template>
        </el-table-column>

        <el-table-column label="IP地址" width="150">
          <template #default="{ row }">
            {{ row.ip_address || "-" }}
          </template>
        </el-table-column>

        <el-table-column label="操作系统" width="150">
          <template #default="{ row }">
            {{ row.os_version || "-" }}
          </template>
        </el-table-column>

        <el-table-column label="最后在线" width="180">
          <template #default="{ row }">
            <span :class="{ 'text-danger': !row.is_online }">
              {{ formatDateTime(row.last_seen) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="客户端版本" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ row.client_version || "未知" }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="配置" width="100" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="showConfig(row)">
              <el-icon><Setting /></el-icon>
            </el-button>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              @click="viewScreenshots(row.client_id)"
            >
              <el-icon><Picture /></el-icon>截图
            </el-button>
            <el-button link type="danger" @click="deleteClient(row)">
              <el-icon><Delete /></el-icon>删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadClients"
          @current-change="loadClients"
        />
      </div>
    </el-card>

    <!-- 客户端配置对话框 -->
    <el-dialog v-model="configVisible" title="客户端配置" width="500px">
      <el-form :model="currentConfig" label-width="100px">
        <el-form-item label="截图间隔">
          <el-input-number
            v-model="currentConfig.interval"
            :min="10"
            :max="3600"
          />
          <span class="unit">秒</span>
        </el-form-item>

        <el-form-item label="图片质量">
          <el-slider
            v-model="currentConfig.quality"
            :min="10"
            :max="100"
            show-input
          />
        </el-form-item>

        <el-form-item label="图片格式">
          <el-radio-group v-model="currentConfig.format">
            <el-radio label="webp">WebP</el-radio>
            <el-radio label="jpg">JPEG</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="心跳保活">
          <el-switch v-model="currentConfig.enable_heartbeat" />
        </el-form-item>

        <el-form-item label="批量上传">
          <el-switch v-model="currentConfig.enable_batch_upload" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" @click="saveConfig" :loading="savingConfig">
          保存配置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Monitor,
  Connection,
  Clock,
  Setting,
  Picture,
  Delete,
} from "@element-plus/icons-vue";
import { clientApi } from "./admin_api";
import dayjs from "dayjs";

const router = useRouter();
const loading = ref(false);
const clients = ref([]);
const total = ref(0);
const currentPage = ref(1);
const pageSize = ref(10);
const showOnlineOnly = ref(false);

const configVisible = ref(false);
const savingConfig = ref(false);
const currentClient = ref(null);
const currentConfig = ref({
  interval: 300,
  quality: 80,
  format: "webp",
  enable_heartbeat: true,
  enable_batch_upload: true,
});

// 统计
const totalClients = computed(() => clients.value.length);
const onlineClients = computed(
  () => clients.value.filter((c) => c.is_online).length,
);
const offlineClients = computed(
  () => clients.value.filter((c) => !c.is_online).length,
);

// 格式化日期时间
const formatDateTime = (datetime) => {
  if (!datetime) return "从未";
  const diff = dayjs().diff(dayjs(datetime), "minute");
  if (diff < 1) return "刚刚";
  if (diff < 60) return `${diff}分钟前`;
  if (diff < 1440) return `${Math.floor(diff / 60)}小时前`;
  return dayjs(datetime).format("YYYY-MM-DD HH:mm");
};

// 加载客户端列表
const loadClients = async () => {
  loading.value = true;
  try {
    const params = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
    };

    if (showOnlineOnly.value) {
      params.online_only = true;
    }

    clients.value = await clientApi.getClients(params);
    total.value = clients.value.length;
  } catch (error) {
    console.error("加载客户端列表失败:", error);
    ElMessage.error("加载客户端列表失败");
  } finally {
    loading.value = false;
  }
};

// 显示配置
const showConfig = (client) => {
  currentClient.value = client;
  currentConfig.value = { ...client.config };
  configVisible.value = true;
};

// 保存配置
const saveConfig = async () => {
  savingConfig.value = true;
  try {
    // TODO: 调用更新配置API
    ElMessage.success("配置已保存");
    configVisible.value = false;
  } catch (error) {
    console.error("保存配置失败:", error);
  } finally {
    savingConfig.value = false;
  }
};

// 查看截图
const viewScreenshots = (clientId) => {
  router.push(`/screenshots?client_id=${clientId}`);
};

// 删除客户端
const deleteClient = (client) => {
  ElMessageBox.confirm(`确定要删除客户端 "${client.client_id}" 吗？`, "警告", {
    confirmButtonText: "确定",
    cancelButtonText: "取消",
    type: "warning",
  }).then(async () => {
    try {
      await clientApi.deleteClient(client.client_id);
      ElMessage.success("删除成功");
      loadClients();
    } catch (error) {
      console.error("删除失败:", error);
    }
  });
};

onMounted(() => {
  loadClients();
});
</script>

<style scoped>
.clients {
  padding: 20px;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  height: 100%;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #333;
  line-height: 1.2;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 14px;
  color: #999;
}

.table-card {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.client-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.client-id {
  font-family: monospace;
  font-size: 13px;
}

.pagination {
  margin-top: 20px;
  text-align: right;
}

.text-danger {
  color: #ff4d4f;
}

.unit {
  margin-left: 8px;
  color: #999;
}
</style>
