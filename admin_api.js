import axios from "axios";
import { ElMessage } from "element-plus";
import router from "./admin_router";

// 创建axios实例
const api = axios.create({
  // 修改这里：使用相对路径，不再需要环境变量
  baseURL: "/api",
  timeout: 30000,
});

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  },
);

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data;
  },
  (error) => {
    if (error.response) {
      switch (error.response.status) {
        case 401:
          ElMessage.error("登录已过期，请重新登录");
          localStorage.removeItem("token");
          localStorage.removeItem("user");
          router.push("/login");
          break;
        case 403:
          ElMessage.error("没有权限执行此操作");
          break;
        case 404:
          ElMessage.error("请求的资源不存在");
          break;
        case 422:
          ElMessage.error("数据验证失败");
          break;
        case 500:
          ElMessage.error("服务器内部错误");
          break;
        default:
          ElMessage.error(error.response.data?.detail || "请求失败");
      }
    } else if (error.request) {
      ElMessage.error("网络连接失败，请检查网络");
    } else {
      ElMessage.error("请求配置错误");
    }
    return Promise.reject(error);
  },
);

// ==================== 认证相关API ====================
export const authApi = {
  login(username, password) {
    const formData = new FormData();
    formData.append("username", username);
    formData.append("password", password);
    return api.post("/auth/login", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  register(userData) {
    return api.post("/auth/register", userData);
  },

  getCurrentUser() {
    return api.get("/auth/me");
  },
};

// ==================== 员工相关API ====================
export const employeeApi = {
  getEmployees(params) {
    return api.get("/employees", { params });
  },

  getEmployee(id) {
    // 对ID进行编码
    const encodedId = encodeURIComponent(id);
    return api.get(`/employees/${encodedId}`);
  },

  createEmployee(data) {
    return api.post("/employees", data);
  },

  updateEmployee(id, data) {
    // ✅ 关键修复：对包含反斜杠的ID进行编码
    const encodedId = encodeURIComponent(id);
    console.log("原始ID:", id); // OS-20250218QMGZ\Administrator
    console.log("编码后:", encodedId); // OS-20250218QMGZ%5CAdministrator
    return api.put(`/employees/${encodedId}`, data);
  },

  deleteEmployee(id) {
    // 删除也需要编码
    const encodedId = encodeURIComponent(id);
    return api.delete(`/employees/${encodedId}`);
  },

  getEmployeeDates(id) {
    // 获取日期也需要编码
    const encodedId = encodeURIComponent(id);
    return api.get(`/employees/${encodedId}/dates`);
  },
};

// ==================== 截图相关API ====================
export const screenshotApi = {
  getScreenshots(params) {
    return api.get("/screenshots", { params });
  },

  getScreenshotsByDate(employeeId, date) {
    return api.get(`/screenshots/${employeeId}/${date}`);
  },

  getRecentScreenshots(limit = 20) {
    return api.get("/screenshots/recent", { params: { limit } });
  },
};

// ==================== 客户端相关API ====================
export const clientApi = {
  getClients(params) {
    return api.get("/clients", { params });
  },

  getOnlineClients() {
    return api.get("/clients/online");
  },

  deleteClient(id) {
    return api.delete(`/clients/${id}`);
  },
};

// ==================== 统计相关API ====================
export const statsApi = {
  getStats() {
    return api.get("/stats");
  },

  getActivities(limit = 50) {
    return api.get("/activities", { params: { limit } });
  },
};

// ==================== 清理相关API ====================
export const cleanupApi = {
  manualCleanup() {
    return api.post("/cleanup");
  },

  getCleanupStatus() {
    return api.get("/cleanup/status");
  },
};

export default api;
