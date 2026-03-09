<template>
  <div class="settings">
    <el-row :gutter="20">
      <!-- 左侧菜单 -->
      <el-col :span="4">
        <el-menu
          :default-active="activeMenu"
          class="settings-menu"
          @select="handleMenuSelect"
        >
          <el-menu-item index="general">
            <el-icon><Setting /></el-icon>
            <span>通用设置</span>
          </el-menu-item>
          <el-menu-item index="cleanup">
            <el-icon><Delete /></el-icon>
            <span>清理策略</span>
          </el-menu-item>
          <el-menu-item index="storage">
            <el-icon><Folder /></el-icon>
            <span>存储设置</span>
          </el-menu-item>
          <el-menu-item index="backup">
            <el-icon><DataLine /></el-icon>
            <span>备份管理</span>
          </el-menu-item>
          <el-menu-item index="security">
            <el-icon><Lock /></el-icon>
            <span>安全设置</span>
          </el-menu-item>
          <el-menu-item index="notification">
            <el-icon><Message /></el-icon>
            <span>通知设置</span>
          </el-menu-item>
        </el-menu>
      </el-col>

      <!-- 右侧内容 -->
      <el-col :span="20">
        <el-card class="settings-content" shadow="hover">
          <!-- 通用设置 -->
          <div v-if="activeMenu === 'general'">
            <h3 class="section-title">通用设置</h3>
            <el-form :model="generalSettings" label-width="120px">
              <el-form-item label="系统名称">
                <el-input
                  v-model="generalSettings.systemName"
                  placeholder="员工监控系统"
                />
              </el-form-item>

              <el-form-item label="默认截图间隔">
                <el-input-number
                  v-model="generalSettings.defaultInterval"
                  :min="10"
                  :max="3600"
                />
                <span class="unit">秒</span>
              </el-form-item>

              <el-form-item label="默认图片格式">
                <el-radio-group v-model="generalSettings.defaultFormat">
                  <el-radio value="webp">WebP (推荐)</el-radio>
                  <el-radio value="jpg">JPEG</el-radio>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="默认图片质量">
                <el-slider
                  v-model="generalSettings.defaultQuality"
                  :min="10"
                  :max="100"
                  show-input
                />
              </el-form-item>

              <el-form-item label="时区">
                <el-select v-model="generalSettings.timezone">
                  <el-option label="UTC+8 (北京时间)" value="Asia/Shanghai" />
                  <el-option label="UTC+0 (伦敦时间)" value="UTC" />
                  <el-option
                    label="UTC-5 (纽约时间)"
                    value="America/New_York"
                  />
                </el-select>
              </el-form-item>
            </el-form>
          </div>

          <!-- 清理策略 -->
          <div v-else-if="activeMenu === 'cleanup'">
            <h3 class="section-title">自动清理策略</h3>

            <el-alert
              title="系统将自动删除超过保留时间的截图，释放存储空间"
              type="info"
              :closable="false"
              show-icon
              class="alert"
            />

            <el-form :model="cleanupSettings" label-width="140px">
              <el-form-item label="启用自动清理">
                <el-switch v-model="cleanupSettings.enabled" />
              </el-form-item>

              <el-form-item label="截图保留时间">
                <el-input-number
                  v-model="cleanupSettings.retentionHours"
                  :min="1"
                  :max="720"
                />
                <span class="unit">小时</span>
              </el-form-item>

              <el-form-item label="清理间隔">
                <el-input-number
                  v-model="cleanupSettings.interval"
                  :min="1"
                  :max="168"
                />
                <span class="unit">小时</span>
              </el-form-item>

              <el-form-item label="清理时间">
                <el-time-picker
                  v-model="cleanupSettings.time"
                  format="HH:mm"
                  placeholder="选择清理时间"
                />
              </el-form-item>

              <el-form-item label="立即清理">
                <el-button
                  type="danger"
                  @click="manualCleanup"
                  :loading="cleaning"
                >
                  立即清理旧截图
                </el-button>
                <span class="help-text">将删除所有超过保留时间的截图</span>
              </el-form-item>
            </el-form>

            <el-divider />

            <h4>当前清理状态</h4>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="上次清理时间">
                {{ cleanupStatus.last_cleanup || "从未" }}
              </el-descriptions-item>
              <el-descriptions-item label="待清理数量">
                {{ cleanupStatus.pending_cleanup }} 张
              </el-descriptions-item>
              <el-descriptions-item label="待清理大小">
                {{ cleanupStatus.pending_size_mb }} MB
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <!-- 存储设置 -->
          <div v-else-if="activeMenu === 'storage'">
            <h3 class="section-title">存储设置</h3>

            <el-progress
              type="dashboard"
              :percentage="storageUsage"
              :color="storageColor"
              class="storage-progress"
            >
              <template #default="{ percentage }">
                <span class="percentage-value">{{ percentage }}%</span>
                <span class="percentage-label">已使用</span>
              </template>
            </el-progress>

            <el-form
              :model="storageSettings"
              label-width="120px"
              class="storage-form"
            >
              <el-form-item label="存储路径">
                <el-input v-model="storageSettings.path" readonly>
                  <template #append>
                    <el-button>浏览</el-button>
                  </template>
                </el-input>
              </el-form-item>

              <el-form-item label="最大存储空间">
                <el-input-number
                  v-model="storageSettings.maxSize"
                  :min="1"
                  :max="1000"
                />
                <span class="unit">GB</span>
              </el-form-item>

              <el-form-item label="缩略图大小">
                <el-input-number
                  v-model="storageSettings.thumbnailSize"
                  :min="100"
                  :max="800"
                  step="50"
                />
                <span class="unit">px</span>
              </el-form-item>

              <el-form-item label="缩略图质量">
                <el-slider
                  v-model="storageSettings.thumbnailQuality"
                  :min="10"
                  :max="100"
                  show-input
                />
              </el-form-item>
            </el-form>
          </div>

          <!-- 备份管理 -->
          <div v-else-if="activeMenu === 'backup'">
            <h3 class="section-title">数据库备份</h3>

            <el-alert
              title="定期备份可以防止数据丢失，建议每周至少备份一次"
              type="warning"
              :closable="false"
              show-icon
              class="alert"
            />

            <el-form :model="backupSettings" label-width="120px">
              <el-form-item label="启用自动备份">
                <el-switch v-model="backupSettings.enabled" />
              </el-form-item>

              <el-form-item label="备份频率">
                <el-select v-model="backupSettings.frequency">
                  <el-option label="每天" value="daily" />
                  <el-option label="每周" value="weekly" />
                  <el-option label="每月" value="monthly" />
                </el-select>
              </el-form-item>

              <el-form-item label="备份时间">
                <el-time-picker
                  v-model="backupSettings.time"
                  format="HH:mm"
                  placeholder="选择备份时间"
                />
              </el-form-item>

              <el-form-item label="保留备份数">
                <el-input-number
                  v-model="backupSettings.keepCount"
                  :min="1"
                  :max="30"
                />
              </el-form-item>

              <el-form-item label="立即备份">
                <el-button
                  type="primary"
                  @click="manualBackup"
                  :loading="backing"
                >
                  立即备份数据库
                </el-button>
              </el-form-item>
            </el-form>

            <el-divider />

            <h4>备份列表</h4>
            <el-table :data="backupList" stripe style="width: 100%">
              <el-table-column prop="filename" label="文件名" />
              <el-table-column prop="size" label="大小" width="100" />
              <el-table-column prop="created_at" label="创建时间" width="180" />
              <el-table-column label="操作" width="150">
                <template #default="{ row }">
                  <el-button link type="primary" @click="downloadBackup(row)"
                    >下载</el-button
                  >
                  <el-button link type="danger" @click="deleteBackup(row)"
                    >删除</el-button
                  >
                </template>
              </el-table-column>
            </el-table>
          </div>

          <!-- 安全设置 -->
          <div v-else-if="activeMenu === 'security'">
            <h3 class="section-title">安全设置</h3>

            <el-tabs type="border-card">
              <el-tab-pane label="管理员密码">
                <el-form
                  :model="passwordForm"
                  label-width="100px"
                  :rules="passwordRules"
                  ref="passwordFormRef"
                >
                  <el-form-item label="当前密码" prop="currentPassword">
                    <el-input
                      v-model="passwordForm.currentPassword"
                      type="password"
                      show-password
                    />
                  </el-form-item>

                  <el-form-item label="新密码" prop="newPassword">
                    <el-input
                      v-model="passwordForm.newPassword"
                      type="password"
                      show-password
                    />
                  </el-form-item>

                  <el-form-item label="确认密码" prop="confirmPassword">
                    <el-input
                      v-model="passwordForm.confirmPassword"
                      type="password"
                      show-password
                    />
                  </el-form-item>

                  <el-form-item>
                    <el-button type="primary" @click="changePassword"
                      >修改密码</el-button
                    >
                  </el-form-item>
                </el-form>
              </el-tab-pane>

              <el-tab-pane label="登录日志">
                <el-table :data="loginLogs" stripe>
                  <el-table-column prop="time" label="时间" width="180" />
                  <el-table-column prop="username" label="用户名" width="120" />
                  <el-table-column prop="ip" label="IP地址" width="150" />
                  <el-table-column prop="result" label="结果" width="100">
                    <template #default="{ row }">
                      <el-tag
                        :type="row.result === '成功' ? 'success' : 'danger'"
                      >
                        {{ row.result }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column
                    prop="user_agent"
                    label="用户代理"
                    show-overflow-tooltip
                  />
                </el-table>
              </el-tab-pane>

              <el-tab-pane label="API密钥">
                <el-form :model="apiKeyForm" label-width="120px">
                  <el-form-item label="当前密钥">
                    <el-input v-model="apiKeyForm.currentKey" readonly>
                      <template #append>
                        <el-button @click="copyApiKey">复制</el-button>
                      </template>
                    </el-input>
                  </el-form-item>

                  <el-form-item label="生成新密钥">
                    <el-button type="warning" @click="regenerateApiKey"
                      >重新生成</el-button
                    >
                    <span class="help-text"
                      >生成后将立即生效，旧密钥将失效</span
                    >
                  </el-form-item>
                </el-form>
              </el-tab-pane>
            </el-tabs>
          </div>

          <!-- 通知设置 -->
          <div v-else-if="activeMenu === 'notification'">
            <h3 class="section-title">通知设置</h3>

            <el-form :model="notificationSettings" label-width="140px">
              <el-form-item label="启用通知">
                <el-switch v-model="notificationSettings.enabled" />
              </el-form-item>

              <el-form-item label="通知方式">
                <el-checkbox-group v-model="notificationSettings.methods">
                  <el-checkbox label="email">邮件</el-checkbox>
                  <el-checkbox label="webhook">Webhook</el-checkbox>
                  <el-checkbox label="dingtalk">钉钉</el-checkbox>
                  <el-checkbox label="wechat">企业微信</el-checkbox>
                </el-checkbox-group>
              </el-form-item>

              <el-form-item label="邮件服务器">
                <el-input
                  v-model="notificationSettings.smtpServer"
                  placeholder="smtp.example.com"
                />
              </el-form-item>

              <el-form-item label="发件人邮箱">
                <el-input
                  v-model="notificationSettings.fromEmail"
                  placeholder="noreply@example.com"
                />
              </el-form-item>

              <el-form-item label="接收邮箱">
                <el-input
                  v-model="notificationSettings.toEmail"
                  placeholder="admin@example.com"
                />
              </el-form-item>

              <el-divider />

              <h4>通知事件</h4>
              <el-form-item label="新客户端注册">
                <el-switch
                  v-model="notificationSettings.events.clientRegister"
                />
              </el-form-item>

              <el-form-item label="客户端离线">
                <el-switch
                  v-model="notificationSettings.events.clientOffline"
                />
              </el-form-item>

              <el-form-item label="存储空间不足">
                <el-switch v-model="notificationSettings.events.lowStorage" />
              </el-form-item>

              <el-form-item label="备份完成">
                <el-switch
                  v-model="notificationSettings.events.backupComplete"
                />
              </el-form-item>
            </el-form>
          </div>

          <!-- 底部按钮 -->
          <el-divider />

          <div class="form-actions">
            <el-button type="primary" @click="saveSettings" :loading="saving">
              保存设置
            </el-button>
            <el-button @click="resetSettings">重置</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Setting,
  Delete,
  Folder,
  DataLine,
  Lock,
  Message,
} from "@element-plus/icons-vue";
import { cleanupApi } from "./admin_api";
import dayjs from "dayjs";

const activeMenu = ref("general");
const saving = ref(false);
const cleaning = ref(false);
const backing = ref(false);

// 通用设置
const generalSettings = ref({
  systemName: "员工监控系统",
  defaultInterval: 60,
  defaultFormat: "webp",
  defaultQuality: 80,
  timezone: "Asia/Shanghai",
});

// 清理设置
const cleanupSettings = ref({
  enabled: true,
  retentionHours: 4,
  interval: 6,
  time: new Date(),
});

const cleanupStatus = ref({
  last_cleanup: null,
  pending_cleanup: 0,
  pending_size_mb: 0,
});

// 存储设置
const storageSettings = ref({
  path: "/data/screenshots",
  maxSize: 100,
  thumbnailSize: 320,
  thumbnailQuality: 75,
});

const storageUsage = ref(45);
const storageColor = computed(() => {
  if (storageUsage.value < 70) return "#52c41a";
  if (storageUsage.value < 85) return "#fa8c16";
  return "#ff4d4f";
});

// 备份设置
const backupSettings = ref({
  enabled: true,
  frequency: "daily",
  time: new Date(),
  keepCount: 7,
});

const backupList = ref([
  {
    filename: "backup_20240101_000000.sql.gz",
    size: "128 MB",
    created_at: "2024-01-01 00:00:00",
  },
]);

// 密码表单
const passwordFormRef = ref(null);
const passwordForm = ref({
  currentPassword: "",
  newPassword: "",
  confirmPassword: "",
});

const passwordRules = {
  currentPassword: [
    { required: true, message: "请输入当前密码", trigger: "blur" },
  ],
  newPassword: [
    { required: true, message: "请输入新密码", trigger: "blur" },
    { min: 6, message: "密码至少6位", trigger: "blur" },
  ],
  confirmPassword: [
    { required: true, message: "请确认新密码", trigger: "blur" },
    {
      validator: (rule, value, callback) => {
        if (value !== passwordForm.value.newPassword) {
          callback(new Error("两次输入的密码不一致"));
        } else {
          callback();
        }
      },
      trigger: "blur",
    },
  ],
};

// 登录日志
const loginLogs = ref([
  {
    time: "2024-01-01 10:30:00",
    username: "admin",
    ip: "192.168.1.100",
    result: "成功",
    user_agent: "Chrome",
  },
]);

// API密钥
const apiKeyForm = ref({
  currentKey: "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
});

// 通知设置
const notificationSettings = ref({
  enabled: true,
  methods: ["email"],
  smtpServer: "",
  fromEmail: "",
  toEmail: "",
  events: {
    clientRegister: true,
    clientOffline: true,
    lowStorage: true,
    backupComplete: true,
  },
});

// 菜单选择
const handleMenuSelect = (index) => {
  activeMenu.value = index;
};

// 手动清理
const manualCleanup = async () => {
  ElMessageBox.confirm(
    "确定要立即清理所有超过保留时间的截图吗？此操作不可恢复！",
    "确认清理",
    {
      confirmButtonText: "确定清理",
      cancelButtonText: "取消",
      type: "warning",
    },
  ).then(async () => {
    cleaning.value = true;
    try {
      const res = await cleanupApi.manualCleanup();
      ElMessage.success(res.message);
      loadCleanupStatus();
    } catch (error) {
      console.error("清理失败:", error);
    } finally {
      cleaning.value = false;
    }
  });
};

// 加载清理状态
const loadCleanupStatus = async () => {
  try {
    cleanupStatus.value = await cleanupApi.getCleanupStatus();
  } catch (error) {
    console.error("加载清理状态失败:", error);
  }
};

// 手动备份
const manualBackup = () => {
  ElMessage.success("备份任务已启动");
};

// 下载备份
const downloadBackup = (row) => {
  ElMessage.success("下载功能开发中...");
};

// 删除备份
const deleteBackup = (row) => {
  ElMessageBox.confirm("确定要删除此备份吗？", "警告", {
    confirmButtonText: "确定",
    cancelButtonText: "取消",
    type: "warning",
  }).then(() => {
    ElMessage.success("删除成功");
  });
};

// 修改密码
const changePassword = async () => {
  if (!passwordFormRef.value) return;

  await passwordFormRef.value.validate((valid) => {
    if (valid) {
      ElMessage.success("密码修改成功");
      passwordForm.value = {
        currentPassword: "",
        newPassword: "",
        confirmPassword: "",
      };
    }
  });
};

// 复制API密钥
const copyApiKey = () => {
  navigator.clipboard.writeText(apiKeyForm.value.currentKey);
  ElMessage.success("已复制到剪贴板");
};

// 重新生成API密钥
const regenerateApiKey = () => {
  ElMessageBox.confirm(
    "重新生成API密钥后，旧密钥将立即失效，确定要继续吗？",
    "确认重新生成",
    {
      confirmButtonText: "确定",
      cancelButtonText: "取消",
      type: "warning",
    },
  ).then(() => {
    apiKeyForm.value.currentKey =
      "sk-" + Math.random().toString(36).substring(2);
    ElMessage.success("新密钥已生成");
  });
};

// 保存设置
const saveSettings = () => {
  saving.value = true;
  setTimeout(() => {
    ElMessage.success("设置已保存");
    saving.value = false;
  }, 1000);
};

// 重置设置
const resetSettings = () => {
  ElMessageBox.confirm("确定要重置所有设置吗？", "警告", {
    confirmButtonText: "确定",
    cancelButtonText: "取消",
    type: "warning",
  }).then(() => {
    ElMessage.success("设置已重置");
  });
};

onMounted(() => {
  loadCleanupStatus();
});
</script>

<style scoped>
.settings {
  padding: 20px;
}

.settings-menu {
  border-radius: 8px;
  border-right: none;
}

.settings-content {
  min-height: 600px;
}

.section-title {
  margin-top: 0;
  margin-bottom: 20px;
  color: #333;
  font-size: 18px;
  font-weight: 500;
}

.alert {
  margin-bottom: 20px;
}

.unit {
  margin-left: 8px;
  color: #999;
}

.help-text {
  margin-left: 12px;
  font-size: 12px;
  color: #999;
}

.storage-progress {
  margin: 20px auto;
  width: 200px;
}

.percentage-value {
  display: block;
  font-size: 28px;
  font-weight: bold;
  color: #333;
}

.percentage-label {
  display: block;
  font-size: 12px;
  color: #999;
  margin-top: 5px;
}

.storage-form {
  margin-top: 20px;
}

.form-actions {
  text-align: center;
}
</style>
