import azure.functions as func
import logging
import json
import pandas as pd
from datetime import datetime
import uuid
import os
from typing import List

# 定义蓝图
bp_consumer = func.Blueprint()

def upload_to_azure(df):

    account_name = os.environ.get("STORAGE_ACCOUNT_NAME")
    account_key = os.environ.get("STORAGE_ACCOUNT_KEY")
    
    storage_options = {
        'account_name': account_name,
        'account_key': account_key
    }
    container_name = 'sbit-project'
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    unique_id = uuid.uuid4().hex[:6]
    file_path = f"az://{container_name}/data_zone/raw/kafka_multiplex_bz/2-user_info_{timestamp}_{unique_id}.json"

    try:
        df.to_json(
            file_path,
            orient='records',
            lines=False,
            storage_options=storage_options
        )
        logging.info(f"成功上传 {len(df)} 条数据至: {file_path}")
    except Exception as e:
        logging.error(f"上传至 Azure 失败: {e}")

@bp_consumer.generic_trigger(    
    arg_name="kevents", 
    type="kafkaTrigger", 
    topic="user_info", 
    brokerList="%KafkaConnString%", 
    username="KafkaUsername",  
    password="KafkaPassword",  
    protocol="SaslSsl",
    authenticationMode="Plain",
    consumerGroup="consumer_group4",
    cardinality="MANY",
    dataType="binary"
    )


def handle_user_info_messages(kevents):
    messages = []
    for event in kevents:
        try:

            body_content = event.get_body().decode('utf-8')

            msg_key = event.key
            if isinstance(msg_key, bytes):
                msg_key = msg_key.decode('utf-8')

            # 3. 提取其他元数据 (直接访问属性，不要加括号)
            msg_dict = {
                "key": msg_key,
                "value": body_content,
                "topic": event.topic,
                "partition": event.partition,
                "offset": event.offset,
                "timestamp": event.timestamp.timestamp() if hasattr(event.timestamp, 'timestamp') else event.timestamp
            }

            messages.append(msg_dict)
            logging.info(f"成功解析消息: Topic={msg_dict['topic']}, Partition={msg_dict['partition']}, Offset={msg_dict['offset']}")

        except Exception as e:
            logging.error(f"解析失败详细原因: {e}")

    if messages:
        # 此时 DataFrame 将包含 key, value, topic, partition, offset, timestamp 六列
        df = pd.DataFrame(messages)
        upload_to_azure(df)




