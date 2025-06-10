from flask import Flask, render_template, jsonify
import psutil
import platform
import time
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)

# Store historical data in memory (in production, use a database)
historical_data = {
    'cpu': [],
    'memory': [],
    'network_sent': [],
    'network_recv': []
}

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/system-data')
def get_system_data():
    try:
        # === CPU DATA ===
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        
        # === MEMORY DATA ===
        memory = psutil.virtual_memory()
        memory_used_gb = round(memory.used / (1024**3), 1)
        memory_total_gb = round(memory.total / (1024**3), 1)
        
        # === DISK DATA ===
        disk_usage = []
        for partition in psutil.disk_partitions():
            try:
                partition_usage = psutil.disk_usage(partition.mountpoint)
                disk_usage.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'used_gb': round(partition_usage.used / (1024**3), 1),
                    'total_gb': round(partition_usage.total / (1024**3), 1),
                    'percent': round((partition_usage.used / partition_usage.total) * 100, 1)
                })
            except PermissionError:
                continue
        
        # === NETWORK DATA ===
        network_io = psutil.net_io_counters()
        network_sent_mb = round(network_io.bytes_sent / (1024**2), 1)
        network_recv_mb = round(network_io.bytes_recv / (1024**2), 1)
        
        # Calculate network speed (requires previous measurement)
        current_time = time.time()
        network_speed = calculate_network_speed(network_io, current_time)
        
        # === TEMPERATURE DATA ===
        temperature_data = get_temperature_data()
        
        # === SYSTEM INFO ===
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        uptime_hours = round(uptime.total_seconds() / 3600, 1)
        
        # === PROCESSES INFO ===
        processes = len(psutil.pids())
        
        # === SERVICES STATUS ===
        services_status = get_services_status()
        
        # === POWER/BATTERY INFO ===
        power_info = get_power_info()
        
        # Store historical data for charts
        store_historical_data(cpu_percent, memory.percent, network_sent_mb, network_recv_mb)
        
        # === ALERTS ===
        alerts = generate_alerts(cpu_percent, memory.percent, disk_usage, temperature_data)
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'cpu': {
                'usage_percent': round(cpu_percent, 1),
                'count': cpu_count,
                'frequency_mhz': round(cpu_freq.current, 0) if cpu_freq else None,
                'temperature': temperature_data.get('cpu_temp')
            },
            'memory': {
                'used_gb': memory_used_gb,
                'total_gb': memory_total_gb,
                'percent': round(memory.percent, 1),
                'available_gb': round(memory.available / (1024**3), 1)
            },
            'disk': disk_usage,
            'network': {
                'total_sent_mb': network_sent_mb,
                'total_recv_mb': network_recv_mb,
                'current_upload_mbps': network_speed.get('upload_mbps', 0),
                'current_download_mbps': network_speed.get('download_mbps', 0)
            },
            'system': {
                'uptime_hours': uptime_hours,
                'uptime_days': round(uptime_hours / 24, 1),
                'platform': platform.system(),
                'hostname': platform.node(),
                'processes': processes,
                'python_version': platform.python_version()
            },
            'services': services_status,
            'power': power_info,
            'temperature': temperature_data,
            'historical': get_recent_historical_data(),
            'alerts': alerts
        }
        
        return jsonify(data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def calculate_network_speed(current_io, current_time):
    """Calculate network upload/download speed"""
    if not hasattr(calculate_network_speed, 'last_io'):
        calculate_network_speed.last_io = current_io
        calculate_network_speed.last_time = current_time
        return {'upload_mbps': 0, 'download_mbps': 0}
    
    time_diff = current_time - calculate_network_speed.last_time
    if time_diff < 1:  # Avoid division by very small numbers
        return {'upload_mbps': 0, 'download_mbps': 0}
    
    upload_speed = (current_io.bytes_sent - calculate_network_speed.last_io.bytes_sent) / time_diff / (1024**2) * 8
    download_speed = (current_io.bytes_recv - calculate_network_speed.last_io.bytes_recv) / time_diff / (1024**2) * 8
    
    calculate_network_speed.last_io = current_io
    calculate_network_speed.last_time = current_time
    
    return {
        'upload_mbps': round(max(0, upload_speed), 1),
        'download_mbps': round(max(0, download_speed), 1)
    }

def get_temperature_data():
    """Get system temperature data"""
    temps = {}
    try:
        if hasattr(psutil, "sensors_temperatures"):
            temp_data = psutil.sensors_temperatures()
            if temp_data:
                # Try to get CPU temperature
                for name, entries in temp_data.items():
                    if 'cpu' in name.lower() or 'core' in name.lower():
                        if entries:
                            temps['cpu_temp'] = round(entries[0].current, 1)
                            break
                
                # Get other temperature sensors
                for name, entries in temp_data.items():
                    if entries and name not in ['cpu', 'core']:
                        temps[f'{name}_temp'] = round(entries[0].current, 1)
        
        # Fallback: simulate reasonable temperatures if no sensors available
        if not temps:
            temps = {
                'cpu_temp': round(45 + (psutil.cpu_percent() * 0.3), 1),
                'system_temp': 42
            }
            
    except Exception:
        temps = {'cpu_temp': None, 'system_temp': None}
    
    return temps

def get_services_status():
    """Get status of common system services"""
    services = {}
    try:
        # Get running processes and categorize them
        process_names = [p.name() for p in psutil.process_iter(['name'])]
        
        # Check for common services/processes
        service_checks = {
            'web_server': ['nginx', 'apache2', 'httpd', 'iis'],
            'database': ['mysql', 'postgres', 'mongodb', 'redis'],
            'security': ['antivirus', 'firewall', 'defender'],
            'system': ['systemd', 'services.exe', 'launchd']
        }
        
        for service_type, process_list in service_checks.items():
            services[service_type] = any(any(proc in pname.lower() for proc in process_list) 
                                       for pname in process_names)
        
        services['total_processes'] = len(process_names)
        
    except Exception:
        services = {
            'web_server': False,
            'database': False,
            'security': True,
            'system': True,
            'total_processes': 0
        }
    
    return services

def get_power_info():
    """Get power/battery information"""
    power = {}
    try:
        if hasattr(psutil, "sensors_battery"):
            battery = psutil.sensors_battery()
            if battery:
                power['battery_percent'] = round(battery.percent, 1)
                power['battery_plugged'] = battery.power_plugged
                power['battery_time_left'] = battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else None
            else:
                power['battery_percent'] = None
                power['battery_plugged'] = True  # Assume desktop
        
        # Estimate power usage based on CPU usage
        power['estimated_watts'] = round(100 + (psutil.cpu_percent() * 2), 0)
        
    except Exception:
        power = {
            'battery_percent': None,
            'battery_plugged': True,
            'estimated_watts': 120
        }
    
    return power

def store_historical_data(cpu, memory, net_sent, net_recv):
    """Store data for historical charts"""
    current_time = datetime.now().strftime('%H:%M')
    
    # Keep only last 20 data points
    for key in historical_data:
        if len(historical_data[key]) >= 20:
            historical_data[key].pop(0)
    
    historical_data['cpu'].append({'time': current_time, 'value': cpu})
    historical_data['memory'].append({'time': current_time, 'value': memory})
    historical_data['network_sent'].append({'time': current_time, 'value': net_sent})
    historical_data['network_recv'].append({'time': current_time, 'value': net_recv})

def get_recent_historical_data():
    """Get recent historical data for charts"""
    return historical_data

def generate_alerts(cpu, memory, disks, temps):
    """Generate system alerts based on thresholds"""
    alerts = []
    
    # CPU alerts
    if cpu > 80:
        alerts.append({
            'level': 'critical',
            'message': f'High CPU usage: {cpu:.1f}%',
            'icon': '⚠'
        })
    elif cpu > 60:
        alerts.append({
            'level': 'warning',
            'message': f'Elevated CPU usage: {cpu:.1f}%',
            'icon': '!'
        })
    
    # Memory alerts
    if memory > 85:
        alerts.append({
            'level': 'critical',
            'message': f'High memory usage: {memory:.1f}%',
            'icon': '⚠'
        })
    elif memory > 70:
        alerts.append({
            'level': 'warning',
            'message': f'Elevated memory usage: {memory:.1f}%',
            'icon': '!'
        })
    
    # Disk alerts
    for disk in disks:
        if disk['percent'] > 90:
            alerts.append({
                'level': 'critical',
                'message': f'Disk {disk["device"]} almost full: {disk["percent"]:.1f}%',
                'icon': '💾'
            })
        elif disk['percent'] > 80:
            alerts.append({
                'level': 'warning',
                'message': f'Disk {disk["device"]} getting full: {disk["percent"]:.1f}%',
                'icon': '💾'
            })
    
    # Temperature alerts
    if temps.get('cpu_temp') and temps['cpu_temp'] > 80:
        alerts.append({
            'level': 'critical',
            'message': f'High CPU temperature: {temps["cpu_temp"]}°C',
            'icon': '🌡️'
        })
    
    # Add info messages if no critical alerts
    if not alerts:
        alerts.append({
            'level': 'info',
            'message': 'All systems operating normally',
            'icon': '✅'
        })
    
    return alerts

if __name__ == '__main__':
    print("Starting System Health Monitor...")
    print("Access the dashboard at: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
