# システム表示順序の定義
SYSTEM_ORDER = ['Fugaku', 'FugakuCN', 'FugakuLN', 'MiyabiG', 'MiyabiC', 'RC_GH200', 'qc-h100']

# システム情報の統一定義
SYSTEM_INFO = {
    'Fugaku': {
        'name': 'Fugaku',
        'cpu_name': 'A64FX',
        'cpu_per_node': 1,
        'cpu_cores': 48,
        'gpu_name': '-',
        'gpu_per_node': '-',
        'memory': '32GB'
    },
    'FugakuCN': {
        'name': 'FugakuCN',
        'cpu_name': 'A64FX',
        'cpu_per_node': 1,
        'cpu_cores': 48,
        'gpu_name': '-',
        'gpu_per_node': '-',
        'memory': '32GB'
    },
    'FugakuLN': {
        'name': 'FugakuLN',
        'cpu_name': 'Intel(R) Xeon(R) Gold 6242 CPU @ 2.80GHz',
        'cpu_per_node': 2,
        'cpu_cores': 16,
        'gpu_name': '-',
        'gpu_per_node': '-',
        'memory': '96GB'
    },
    'qc-h100': {
        'name': 'qc-h100',
        'cpu_name': 'AMD EPYC 9534',
        'cpu_per_node': 2,
        'cpu_cores': 64,
        'gpu_name': 'NVIDIA H100',
        'gpu_per_node': 4,
        'memory': '256GB'
    },
    'MiyabiG': {
        'name': 'MiyabiG',
        'cpu_name': 'NVIDIA Grace CPU',
        'cpu_per_node': 1,
        'cpu_cores': 72,
        'gpu_name': 'NVIDIA Hopper H100 GPU',
        'gpu_per_node': 1,
        'memory': '120GB'
    },
    'MiyabiC': {
        'name': 'MiyabiC',
        'cpu_name': 'Intel Xeon Max 9480',
        'cpu_per_node': 2,
        'cpu_cores': 112,
        'gpu_name': '-',
        'gpu_per_node': '-',
        'memory': '128GB'
    },
    'RC_GH200': {
        'name': 'RC_GH200',
        'cpu_name': 'NVIDIA Grace CPU',
        'cpu_per_node': 1,
        'cpu_cores': 72,
        'gpu_name': 'NVIDIA Hopper H100 GPU',
        'gpu_per_node': 1,
        'memory': '120GB'
    }
}

def get_system_info(system_name):
    """指定されたシステム名の情報を取得"""
    return SYSTEM_INFO.get(system_name, {
        'name': system_name,
        'cpu_name': 'Unknown System',
        'cpu_per_node': '-',
        'cpu_cores': '-',
        'gpu_name': '-',
        'gpu_per_node': '-',
        'memory': '-'
    })

def get_all_systems_info():
    """全システム情報を順序付きで取得"""
    ordered_systems = {}
    # 定義された順序で追加
    for system_name in SYSTEM_ORDER:
        if system_name in SYSTEM_INFO:
            ordered_systems[system_name] = SYSTEM_INFO[system_name]
    
    # 順序に含まれていないシステムも追加
    for system_name, info in SYSTEM_INFO.items():
        if system_name not in ordered_systems:
            ordered_systems[system_name] = info
    
    return ordered_systems