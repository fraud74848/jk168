#!/usr/bin/env python3
"""
数据库初始化脚本
"""

import os
from app import app, db
from models import User, Employee, Client, Screenshot

def init_database():
    """初始化数据库"""
    with app.app_context():
        # 创建所有表
        db.create_all()
        print("✅ 数据库表创建成功")
        
        # 创建默认管理员
        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
        
        admin = User.query.filter_by(username=admin_username).first()
        if not admin:
            admin = User(username=admin_username)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"✅ 默认管理员已创建: {admin_username}")
        
        # 创建示例员工（可选）
        if Employee.query.count() == 0:
            demo_employees = [
                {
                    'employee_id': 'DEMO001',
                    'name': '张三',
                    'department': '技术部',
                    'position': '开发工程师',
                    'status': 'active'
                },
                {
                    'employee_id': 'DEMO002',
                    'name': '李四',
                    'department': '产品部',
                    'position': '产品经理',
                    'status': 'active'
                }
            ]
            
            for emp_data in demo_employees:
                emp = Employee(**emp_data)
                db.session.add(emp)
            
            db.session.commit()
            print(f"✅ 示例员工已创建")
        
        # 统计表数量
        users = User.query.count()
        employees = Employee.query.count()
        clients = Client.query.count()
        screenshots = Screenshot.query.count()
        
        print(f"\n📊 当前数据统计:")
        print(f"   - 用户数: {users}")
        print(f"   - 员工数: {employees}")
        print(f"   - 客户端数: {clients}")
        print(f"   - 截图数: {screenshots}")
        
        print(f"\n🎉 数据库初始化完成！")

if __name__ == '__main__':
    init_database()