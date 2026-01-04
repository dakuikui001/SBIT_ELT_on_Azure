import azure.functions as func
import logging
import json
import os
from confluent_kafka import Producer

# 定义蓝图
bp_producer = func.Blueprint()

# 共享的 Producer 实例化函数
def get_kafka_producer():
    conf = {
        'bootstrap.servers': os.environ.get("KafkaConnString"),
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': os.environ.get("KafkaUsername"),
        'sasl.password': os.environ.get("KafkaPassword")
    }
    return Producer(conf)

def delivery_status(err, msg):
    if err:
        logging.error(f'Kafka 交付失败: {err}')
    else:
        logging.info(f'Kafka 交付成功: topic:{msg.topic()}, partition:{msg.partition()}, offset:{msg.offset()}')

# ==========================================
# Blob Trigger: 监听 ADLS 文件夹
# ==========================================
@bp_producer.blob_trigger(
    arg_name="myblob", 
    path="sbit-project/data_zone/input/4-workout_{name}.json",  # 监听 sbit-project 容器下的 input_zone 文件夹
    connection="STORAGE_ACCOUNT_CONNECTION"      # local.settings.json 中的存储连接字符串
)
def process_blob_to_kafka(myblob: func.InputStream):
    logging.info(f"检测到新文件上传: {myblob.name}, 大小: {myblob.length} bytes")

    try:
        # 1. 读取文件内容并解析
        # myblob 会自动作为流被读取
        blob_content = myblob.read().decode('utf-8')
        json_data = json.loads(blob_content)

        # 兼容列表和单个对象
        if not isinstance(json_data, list):
            records = [json_data]
        else:
            records = json_data

        producer = get_kafka_producer()
        topic = 'workout'

        # 2. 循环发送至 Kafka
        for record in records:
            # 如果 record 还是字符串则再转一次字典
            data = json.loads(record) if isinstance(record, str) else record
            
            msg_key = str(data.get('workout_id', 'unknown')).encode('utf-8')
            msg_value = json.dumps(data).encode('utf-8')

            producer.produce(
                topic, 
                key=msg_key, 
                value=msg_value, 
                callback=delivery_status
            )
            producer.poll(0)

        producer.flush()
        logging.info(f"文件 {myblob.name} 中的 {len(records)} 条记录已成功转发至 Kafka")

    except Exception as e:
        logging.error(f"处理 Blob 文件失败: {str(e)}")