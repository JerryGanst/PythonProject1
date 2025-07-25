#!/usr/bin/env python3
"""
商品价格报告生成系统
功能：定时/实时获取商品价格数据，生成报告和图表
"""

import requests
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import schedule
import time
import json
import logging
from pathlib import Path
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CommodityPriceClient:
    """商品价格API客户端"""
    
    def __init__(self, api_key, base_url="https://commodities-api.com/api", commodity_symbols=None):
        self.api_key = api_key
        self.base_url = base_url
        self.commodity_symbols = commodity_symbols or {}
        self.last_call_time = 0
        self.call_interval = 0  # 取消限流
        
    def _rate_limit(self):
        """限流控制"""
        current_time = time.time()
        time_since_last_call = current_time - self.last_call_time
        if time_since_last_call < self.call_interval:
            sleep_time = self.call_interval - time_since_last_call
            logger.info(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_call_time = time.time()
    
    def get_current_price(self, commodity):
        """获取当前价格"""
        self._rate_limit()
        
        try:
            # 获取商品符号
            symbol = self.commodity_symbols.get(commodity, commodity.upper())
            
            url = f"{self.base_url}/latest"
            params = {
                'access_key': self.api_key,
                'symbols': symbol
            }
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if data.get('success') and 'rates' in data and symbol in data['rates']:
                return {
                    'commodity': commodity,
                    'price': data['rates'][symbol],
                    'exchange': 'Commodities-API',
                    'timestamp': datetime.now(),
                    'unix_timestamp': data.get('timestamp', int(time.time()))
                }
            else:
                logger.error(f"API响应无效 - 商品: {commodity} ({symbol}), 响应: {data}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"API请求超时 - 商品: {commodity}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"网络连接错误 - 商品: {commodity}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP错误 - 商品: {commodity}, 状态码: {e.response.status_code}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败 - 商品: {commodity}, 错误: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON解析失败 - 商品: {commodity}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"获取价格时发生未知错误 - 商品: {commodity}, 错误: {e}")
            return None
    
    def get_historical_prices(self, commodity, days=7):
        """获取历史价格"""
        self._rate_limit()
        
        try:
            # 获取商品符号
            symbol = self.commodity_symbols.get(commodity, commodity.upper())
            
            # 计算日期范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            url = f"{self.base_url}/timeseries"
            params = {
                'access_key': self.api_key,
                'symbols': symbol,
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            }
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if data.get('success'):
                return data.get('rates', {})
            else:
                logger.error(f"历史数据API响应无效 - 商品: {commodity} ({symbol}), 响应: {data}")
                return {}
            
        except requests.exceptions.Timeout:
            logger.error(f"历史数据API请求超时 - 商品: {commodity}")
            return {}
        except requests.exceptions.ConnectionError:
            logger.error(f"历史数据网络连接错误 - 商品: {commodity}")
            return {}
        except requests.exceptions.HTTPError as e:
            logger.error(f"历史数据HTTP错误 - 商品: {commodity}, 状态码: {e.response.status_code}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"历史数据API请求失败 - 商品: {commodity}, 错误: {e}")
            return {}
        except ValueError as e:
            logger.error(f"历史数据JSON解析失败 - 商品: {commodity}, 错误: {e}")
            return {}
        except Exception as e:
            logger.error(f"获取历史数据时发生未知错误 - 商品: {commodity}, 错误: {e}")
            return {}

class CommodityDataManager:
    """数据管理器"""
    
    def __init__(self, data_file="commodity_data.json"):
        self.data_file = Path(data_file)
        self.data = self._load_data()
    
    def _load_data(self):
        """加载历史数据"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"成功加载历史数据：{len(data)} 个商品")
                return data
            except json.JSONDecodeError as e:
                logger.error(f"JSON文件损坏，无法解析：{self.data_file}, 错误: {e}")
                # 尝试备份损坏的文件
                backup_file = self.data_file.with_suffix('.backup')
                try:
                    self.data_file.rename(backup_file)
                    logger.info(f"损坏的数据文件已备份到：{backup_file}")
                except Exception:
                    pass
                return {}
            except PermissionError:
                logger.error(f"权限不足，无法读取数据文件：{self.data_file}")
                return {}
            except Exception as e:
                logger.error(f"加载数据文件时发生错误：{self.data_file}, 错误: {e}")
                return {}
        else:
            logger.info("数据文件不存在，将创建新的数据存储")
            return {}
    
    def save_data(self):
        """保存数据"""
        try:
            # 先保存到临时文件，然后重命名，确保原子性操作
            temp_file = self.data_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, default=str, indent=2, ensure_ascii=False)
            
            # 原子性重命名
            temp_file.replace(self.data_file)
            logger.debug(f"数据已保存到 {self.data_file}")
            
        except PermissionError:
            logger.error(f"保存数据失败：权限不足 - {self.data_file}")
        except OSError as e:
            logger.error(f"保存数据失败：磁盘错误 - {self.data_file}, 错误: {e}")
        except Exception as e:
            logger.error(f"保存数据失败：未知错误 - {self.data_file}, 错误: {e}")
            # 清理临时文件
            temp_file = self.data_file.with_suffix('.tmp')
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except:
                    pass
    
    def add_price_data(self, commodity, price_data):
        """添加价格数据"""
        if commodity not in self.data:
            self.data[commodity] = []
        
        self.data[commodity].append({
            'price': price_data['price'],
            'timestamp': price_data['timestamp'].isoformat(),
            'exchange': price_data['exchange']
        })
        
        # 保留最近30天的数据
        cutoff_date = datetime.now() - timedelta(days=30)
        self.data[commodity] = [
            d for d in self.data[commodity] 
            if datetime.fromisoformat(d['timestamp']) > cutoff_date
        ]
    
    def get_dataframe(self, commodity):
        """获取DataFrame格式数据"""
        if commodity not in self.data or not self.data[commodity]:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.data[commodity])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        return df

class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, data_manager, output_dir="reports"):
        self.data_manager = data_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 设置中文字体和样式
        plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        sns.set_style("whitegrid")
    
    def generate_price_chart(self, commodity, days=7):
        """生成价格走势图"""
        df = self.data_manager.get_dataframe(commodity)
        if df.empty:
            logger.warning(f"No data available for {commodity}")
            return None
        
        # 过滤指定天数的数据
        cutoff_date = datetime.now() - timedelta(days=days)
        df = df[df['timestamp'] > cutoff_date]
        
        if df.empty:
            logger.warning(f"No recent data available for {commodity}")
            return None
        
        # 创建图表
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['price'],
            mode='lines+markers',
            name=f'{commodity.upper()} Price',
            line=dict(color='#1f77b4', width=3),
            marker=dict(size=6)
        ))
        
        # 计算价格变化
        if len(df) > 1:
            price_change = df['price'].iloc[-1] - df['price'].iloc[0]
            change_percent = (price_change / df['price'].iloc[0]) * 100
            
            color = 'green' if price_change >= 0 else 'red'
            arrow = '↗' if price_change >= 0 else '↘'
            
            fig.add_annotation(
                x=df['timestamp'].iloc[-1],
                y=df['price'].iloc[-1],
                text=f"{arrow} {change_percent:+.2f}%",
                showarrow=True,
                arrowhead=2,
                arrowcolor=color,
                font=dict(size=14, color=color)
            )
        
        fig.update_layout(
            title=f'{commodity.upper()} 价格走势 ({days}天)',
            xaxis_title='时间',
            yaxis_title='价格 (USD)',
            template='plotly_white',
            height=500,
            showlegend=True
        )
        
        # 保存图表
        chart_file = self.output_dir / f"{commodity}_price_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        fig.write_html(chart_file)
        logger.info(f"Chart saved to {chart_file}")
        
        return chart_file
    
    def generate_comparison_chart(self, commodities):
        """生成多商品对比图"""
        fig = make_subplots(
            rows=len(commodities), cols=1,
            subplot_titles=[f'{c.upper()} Price' for c in commodities],
            vertical_spacing=0.08
        )
        
        for i, commodity in enumerate(commodities, 1):
            df = self.data_manager.get_dataframe(commodity)
            if not df.empty:
                fig.add_trace(
                    go.Scatter(
                        x=df['timestamp'],
                        y=df['price'],
                        mode='lines',
                        name=commodity.upper(),
                        line=dict(width=2)
                    ),
                    row=i, col=1
                )
        
        fig.update_layout(
            title='商品价格对比',
            height=200 * len(commodities),
            template='plotly_white'
        )
        
        # 保存对比图
        chart_file = self.output_dir / f"commodity_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        fig.write_html(chart_file)
        logger.info(f"Comparison chart saved to {chart_file}")
        
        return chart_file
    
    def generate_summary_report(self, commodities):
        """生成汇总报告"""
        report_data = []
        
        for commodity in commodities:
            df = self.data_manager.get_dataframe(commodity)
            if not df.empty and len(df) > 1:
                current_price = df['price'].iloc[-1]
                prev_price = df['price'].iloc[0]
                change = current_price - prev_price
                change_percent = (change / prev_price) * 100
                
                report_data.append({
                    '商品': commodity.upper(),
                    '当前价格': f"${current_price:.2f}",
                    '变化金额': f"${change:+.2f}",
                    '变化百分比': f"{change_percent:+.2f}%",
                    '最高价': f"${df['price'].max():.2f}",
                    '最低价': f"${df['price'].min():.2f}",
                    '更新时间': df['timestamp'].iloc[-1].strftime('%Y-%m-%d %H:%M:%S')
                })
        
        if report_data:
            df_report = pd.DataFrame(report_data)
            
            # 保存CSV报告
            csv_file = self.output_dir / f"commodity_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df_report.to_csv(csv_file, index=False, encoding='utf-8-sig')
            
            # 生成HTML报告
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>商品价格报告</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    table {{ border-collapse: collapse; width: 100%; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
                    th {{ background-color: #f2f2f2; }}
                    .positive {{ color: green; }}
                    .negative {{ color: red; }}
                </style>
            </head>
            <body>
                <h1>商品价格报告</h1>
                <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                {df_report.to_html(index=False, escape=False, classes='table')}
            </body>
            </html>
            """
            
            html_file = self.output_dir / f"commodity_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            logger.info(f"Reports saved to {csv_file} and {html_file}")
            return csv_file, html_file
        
        return None, None

class CommodityReportSystem:
    """主系统类"""
    
    def __init__(self, api_key, commodities=['gold', 'silver', 'crude_oil', 'natural_gas'], commodity_symbols=None):
        self.client = CommodityPriceClient(api_key, commodity_symbols=commodity_symbols)
        self.data_manager = CommodityDataManager()
        self.report_generator = ReportGenerator(self.data_manager)
        self.commodities = commodities
    
    def collect_current_prices(self):
        """收集当前价格"""
        logger.info("开始收集商品价格数据...")
        
        success_count = 0
        total_count = len(self.commodities)
        
        for commodity in self.commodities:
            try:
                price_data = self.client.get_current_price(commodity)
                if price_data:
                    self.data_manager.add_price_data(commodity, price_data)
                    logger.info(f"{commodity}: ${price_data['price']:.2f}")
                    success_count += 1
                else:
                    logger.warning(f"未能获取 {commodity} 的价格数据")
            except Exception as e:
                logger.error(f"处理商品 {commodity} 时发生错误: {e}")
        
        try:
            self.data_manager.save_data()
            logger.info(f"价格数据收集完成 - 成功: {success_count}/{total_count}")
        except Exception as e:
            logger.error(f"保存价格数据时发生错误: {e}")
            
        if success_count == 0:
            logger.error("警告：未能收集到任何商品的价格数据！")
    
    def generate_reports(self):
        """生成所有报告"""
        logger.info("开始生成报告...")
        
        report_success_count = 0
        total_reports = 3 + len(self.commodities)  # 汇总报告 + 单个商品图表 + 对比图表
        
        # 生成汇总报告
        try:
            csv_file, html_file = self.report_generator.generate_summary_report(self.commodities)
            if csv_file and html_file:
                logger.info("汇总报告生成成功")
                report_success_count += 1
            else:
                logger.warning("汇总报告生成失败或无数据")
        except Exception as e:
            logger.error(f"生成汇总报告时发生错误: {e}")
        
        # 生成单个商品图表
        for commodity in self.commodities:
            try:
                chart_file = self.report_generator.generate_price_chart(commodity, days=7)
                if chart_file:
                    logger.debug(f"{commodity} 价格图表生成成功")
                    report_success_count += 1
                else:
                    logger.warning(f"{commodity} 价格图表生成失败")
            except Exception as e:
                logger.error(f"生成 {commodity} 价格图表时发生错误: {e}")
        
        # 生成对比图表
        try:
            comparison_file = self.report_generator.generate_comparison_chart(self.commodities)
            if comparison_file:
                logger.info("对比图表生成成功")
                report_success_count += 1
            else:
                logger.warning("对比图表生成失败")
        except Exception as e:
            logger.error(f"生成对比图表时发生错误: {e}")
        
        logger.info(f"报告生成完成 - 成功: {report_success_count}/{total_reports}")
        
        if report_success_count == 0:
            logger.error("警告：未能生成任何报告！")
    
    def run_scheduled_tasks(self):
        """运行定时任务"""
        logger.info("启动商品价格报告系统...")
        
        # 立即执行一次
        self.collect_current_prices()
        self.generate_reports()
        
        # 设置定时任务
        schedule.every().hour.do(self.collect_current_prices)  # 每小时收集数据
        schedule.every().day.at("08:00").do(self.generate_reports)  # 每天8点生成报告
        schedule.every().day.at("18:00").do(self.generate_reports)  # 每天18点生成报告
        
        logger.info("定时任务已设置: 每小时收集数据，每天8:00和18:00生成报告")
        
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
            except Exception as e:
                logger.error(f"定时任务执行出错: {e}")
                logger.info("系统将在60秒后重试...")
                time.sleep(60)

def main():
    """主函数"""
    try:
        from config import API_KEY, DEFAULT_COMMODITIES, COMMODITY_SYMBOLS
    except ImportError as e:
        logger.error(f"配置文件加载失败: {e}")
        logger.error("请确保 config.py 文件存在且格式正确")
        return
    except Exception as e:
        logger.error(f"配置加载异常: {e}")
        return
    
    # 验证必要的配置
    try:
        if not API_KEY:
            raise ValueError("API_KEY 不能为空")
        if not DEFAULT_COMMODITIES:
            raise ValueError("DEFAULT_COMMODITIES 不能为空")
    except (NameError, ValueError) as e:
        logger.error(f"配置验证失败: {e}")
        logger.error("请检查 config.py 中的 API_KEY 和 DEFAULT_COMMODITIES 设置")
        return
    
    # 创建系统实例
    try:
        system = CommodityReportSystem(API_KEY, DEFAULT_COMMODITIES, COMMODITY_SYMBOLS)
    except Exception as e:
        logger.error(f"系统初始化失败: {e}")
        return
    
    # 启动定时任务
    try:
        system.run_scheduled_tasks()
    except KeyboardInterrupt:
        logger.info("系统停止")
    except Exception as e:
        logger.error(f"系统运行异常: {e}")
        logger.info("系统将退出")

if __name__ == "__main__":
    main()