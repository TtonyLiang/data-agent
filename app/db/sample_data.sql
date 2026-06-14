-- 示例业务数据库 (电商)
CREATE DATABASE IF NOT EXISTS business_db DEFAULT CHARACTER SET utf8mb4;
USE business_db;

-- 产品表
CREATE TABLE IF NOT EXISTS products (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(256) NOT NULL COMMENT '产品名称',
    category VARCHAR(128) COMMENT '产品类别',
    price DECIMAL(10,2) COMMENT '单价',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='产品表';

-- 订单表
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_no VARCHAR(64) NOT NULL COMMENT '订单号',
    user_id BIGINT NOT NULL COMMENT '用户ID',
    product_id BIGINT NOT NULL COMMENT '产品ID',
    quantity INT DEFAULT 1 COMMENT '数量',
    amount DECIMAL(10,2) NOT NULL COMMENT '订单金额',
    status TINYINT DEFAULT 1 COMMENT '状态: 0待支付 1已支付 2已取消 3退款中',
    region VARCHAR(64) COMMENT '地区',
    order_date DATE COMMENT '订单日期',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id),
    INDEX idx_order_date (order_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(128) NOT NULL COMMENT '用户名',
    email VARCHAR(256) COMMENT '邮箱',
    phone VARCHAR(32) COMMENT '手机号',
    region VARCHAR(64) COMMENT '地区',
    vip_level TINYINT DEFAULT 0 COMMENT 'VIP等级',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- 插入示例数据
INSERT INTO products (name, category, price) VALUES
('iPhone 16', '手机', 6999.00),
('MacBook Pro', '电脑', 14999.00),
('AirPods Pro', '配件', 1899.00),
('iPad Air', '平板', 4799.00),
('Apple Watch', '穿戴', 2999.00);

INSERT INTO users (username, email, region, vip_level) VALUES
('张三', 'zhangsan@example.com', '华东', 3),
('李四', 'lisi@example.com', '华南', 1),
('王五', 'wangwu@example.com', '华北', 2),
('赵六', 'zhaoliu@example.com', '华东', 0),
('孙七', 'sunqi@example.com', '西南', 1);

INSERT INTO orders (order_no, user_id, product_id, quantity, amount, status, region, order_date) VALUES
('ORD001', 1, 1, 1, 6999.00, 1, '华东', '2026-05-01'),
('ORD002', 2, 2, 1, 14999.00, 1, '华南', '2026-05-02'),
('ORD003', 1, 3, 2, 3798.00, 1, '华东', '2026-05-03'),
('ORD004', 3, 4, 1, 4799.00, 0, '华北', '2026-05-04'),
('ORD005', 4, 1, 1, 6999.00, 1, '华东', '2026-05-05'),
('ORD006', 5, 5, 1, 2999.00, 2, '西南', '2026-05-06'),
('ORD007', 2, 3, 1, 1899.00, 1, '华南', '2026-05-07'),
('ORD008', 3, 2, 1, 14999.00, 1, '华北', '2026-05-08'),
('ORD009', 1, 4, 1, 4799.00, 1, '华东', '2026-05-09'),
('ORD010', 4, 5, 2, 5998.00, 1, '华东', '2026-05-10');
