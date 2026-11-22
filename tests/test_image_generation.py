"""Offline image API transport and validation contracts."""
import base64
import io
import json
import threading
import unittest
from unittest.mock import patch
from PySide6.QtCore import QBuffer,QByteArray,QIODevice
from PySide6.QtGui import QColor,QImage
from agentnik import core,image_generation as images

C={'url':'https://openrouter.ai/api/v1','protocol':'messages','api_key':'fixture-key'}


def png():
    image=QImage(3,2,QImage.Format.Format_ARGB32);image.fill(QColor('red'))
    array=QByteArray();buffer=QBuffer(array);buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG');buffer.close()
    return bytes(array)


class ImageAPI(unittest.TestCase):
    def test_generate_and_edit_use_image_endpoint_and_bearer_connection(self):
        image=png();payload={'data':[{'b64_json':base64.b64encode(image).decode(),'media_type':'image/png'}],'usage':{'cost':.04}}
        with patch.object(core,'open_request',return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result=images.generate(C,'image/model','Make it blue',[image],aspect_ratio='16:9',background='transparent')
        connection,url,body=request.call_args.args
        self.assertEqual(url,'https://openrouter.ai/api/v1/images');self.assertEqual(connection['protocol'],'responses')
        self.assertEqual(core.headers(connection)['Authorization'],'Bearer fixture-key')
        self.assertEqual(body['input_references'][0]['image_url']['url'],'data:image/png;base64,'+base64.b64encode(image).decode())
        self.assertEqual(body['aspect_ratio'],'16:9');self.assertEqual(result,{'data':image,'mime':'image/png','suffix':'.png','cost':.04})

    def test_explicit_gateway_endpoint_and_model_listing(self):
        c={'url':'https://gateway.example/v1','api_key':'k'};endpoint='https://gateway.example:4000/openrouter/v1/images'
        with patch.object(core,'open_request',return_value=io.BytesIO(b'{"data":[{"id":"vendor/model"}]}')) as request:
            self.assertEqual(images.list_models(c,endpoint),['vendor/model'])
        self.assertEqual(request.call_args.args[1],endpoint+'/models')
        for invalid in ('https://evil.example/v1/images','http://gateway.example/v1/images','https://user@gateway.example/images','https://gateway.example/images?key=secret'):
            with self.subTest(endpoint=invalid),self.assertRaises(ValueError):images.image_endpoint(c,invalid)

    def test_invalid_outputs_and_oversized_data_are_rejected(self):
        examples=[{'data':[{'b64_json':'not base64!'}]},{'data':[{'b64_json':base64.b64encode(b'not an image').decode()}]},
                  {'data':[{'b64_json':base64.b64encode(png()).decode(),'media_type':'image/jpeg'}]}, {'data':[]}]
        for payload in examples:
            with self.subTest(payload=payload),patch.object(core,'open_request',return_value=io.BytesIO(json.dumps(payload).encode())),self.assertRaises(images.ImageRequestError):images.generate(C,'model','prompt')
        with patch.object(images,'MAX_RESPONSE_BYTES',10),patch.object(core,'open_request',return_value=io.BytesIO(b'x'*11)),self.assertRaises(images.ImageRequestError):images.generate(C,'model','prompt')

    def test_failure_does_not_retry_or_expose_server_or_key(self):
        for exc,kind in ((core.EndpointError(403,'fixture-key private detail'),images.ImageRequestError),(core.EndpointError(500,'fixture-key private detail'),images.ImageRequestUncertain),(TimeoutError('fixture-key'),images.ImageRequestUncertain)):
            with self.subTest(kind=kind),patch.object(core,'open_request',side_effect=exc) as request:
                with self.assertRaises(kind) as result:images.generate(C,'model','prompt')
                self.assertNotIn('fixture-key',str(result.exception));request.assert_called_once()
        cancel=threading.Event();cancel.set()
        with patch.object(core,'open_request') as request,self.assertRaises(InterruptedError):images.generate(C,'model','prompt',cancel=cancel)
        request.assert_not_called()


if __name__=='__main__':unittest.main()
